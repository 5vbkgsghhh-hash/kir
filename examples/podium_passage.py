"""Mission 1 acceptance scene: podium with atrium, passage, body in a void, nested body.

    python examples/podium_passage.py NEW.sqlite

🔴 WHY THIS SCENE, NOT THE RESIDENTIAL EXAMPLE. The smoothed podium
(`bulge_mm=2000`, `ThruSections(solid, ruled=False)`) has no closed-form
analytics: the loft's volume between five sections is not computed by a
formula, and there would be nothing to check OCCT against except OCCT itself.
At `bulge_mm=0` all five sections COINCIDE, the loft degenerates into an
exact right prism — and the whole scene becomes a set of boxes and one
cylinder, whose volume and gap are computed on paper.

The podium recipe is the SAME ONE (`residential_with_podium.build_podium_body`),
and this is not a convenience: a private copy of the recipe would mean
acceptance judges a different body than the product. The recipe's range
allows this parameter (`0 <= bulge <= 4000`).

REFERENCE VALUES (closed-form formula; independently computed by the
acceptance instrument — oracles A and B):
    podium box volume             3.819000e+12 mm³
    atrium cylinder                5.890486e+10 mm³   (π·2500²·3000)
    podium with a hole             3.760095e+12 mm³
    passage ∩ podium               3.800000e+10 mm³ = 38.000000 m³   (4000 × 19000 × 500)
    penetration depth              500.000 mm exactly
    in_atrium: gap to the wall     1085.786438 mm  = 2500 − 1000·√2 → NO intersection
    inside ∩ pier                  1.000000e+09 mm³ = 1.000000 m³, face intersections 0

WHAT THIS SCENE DOES NOT CLAIM: it is not BIM and has not gone through
Revit; bodies are declared as `create_directshape` with category `mass`, the
podium/passage contact is a fact about the SAVED shape of the project, not
about a built model. This file does not touch the existing examples or their
store fixtures.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys

#: Scene coordinates. One source for the example and for the acceptance
#: instrument (`.work/…/geo-loop/acceptance/oracles.py` holds the same
#: numbers): were they to diverge, they would judge different scenes, and the
#: "38 m³ reference" would stop meaning anything.
PODIUM_PARAMETERS = {"height_mm": 3000., "bulge_mm": 0., "atrium_radius_mm": 2500.}
PASSAGE = ((30000., -6000., -500.), (34000., 15000., 2500.))
IN_ATRIUM = ((18000., 3500., -2500.), (20000., 5500., -500.))
PIER = ((40000., 0., -3000.), (46000., 6000., 0.))
INSIDE = ((42500., 2500., -2000.), (43500., 3500., -1000.))

BODIES = (("podium", None), ("passage", PASSAGE), ("in_atrium", IN_ATRIUM),
          ("pier", PIER), ("inside", INSIDE))

def scene_parameters() -> dict:
    """`{body name: parameters of ITS instance}` — one set per body."""
    return {"podium": {"podium": dict(PODIUM_PARAMETERS)},
            "passage": {"passage": [list(PASSAGE[0]), list(PASSAGE[1])]},
            "in_atrium": {"in_atrium": [list(IN_ATRIUM[0]), list(IN_ATRIUM[1])]},
            "pier": {"pier": [list(PIER[0]), list(PIER[1])]},
            "inside": {"inside": [list(INSIDE[0]), list(INSIDE[1])]}}


def rebuild_body(output_key, box, parameters, *, project_id=None, instance_key=None,
                 frame=None):
    """Rebuild the output's body from a NEW box. Called from `kir.project_fix`.

    `parameters` is the FULL new set of instance parameters: the store checks
    the asset's inputs against the owning instance's inputs and rejects a
    mismatch.

    🔴 `frame` IS ACCEPTED AND PASSED ON. `capture_body` sets an IDENTITY
    frame by default, and a callback that did not accept it would silently
    unrotate a rotated body: the fix would move not only the position but
    also the coordinate system. This example's scene stands with an identity
    frame, so the number does not change here; the line exists so it also
    does not change for a rotated one (`kir.project_fix` checks the frame
    after the recompute and refuses).
    """
    from kir.occt_geometry import IDENTITY_FRAME, capture_body

    return capture_body(_box(box), project_id=project_id or PROJECT_ID,
                        instance_key=instance_key or output_key, output_key=output_key,
                        recipe=_pin(), parameters=parameters,
                        frame=tuple(frame) if frame else IDENTITY_FRAME,
                        linear_deflection_mm=40.)


PROJECT_ID = "podium-passage"
MODULE = "podium-passage-scene-v1"

#: 🔴 EACH BODY HAS ITS OWN INSTANCE, AND THIS IS A DECISION, NOT STYLING.
#: Parameters belong to the INSTANCE, and the store checks each asset's
#: inputs against its owner's inputs (`parameters_mismatch`). Keep all five
#: bodies in one instance, and editing ONE passage's box would make the
#: bundles of all four neighbors foreign: fixing one finding would require
#: recomputing the whole scene. Separating instances is exactly what turns a
#: "fix" into an edit of ONE authored parameter.
INSTANCE_OF = {key: key for key, _ in BODIES}


def _pin():
    from kir.occt_geometry import OCP_VERSION
    from kir.project import RecipePin

    source = Path(__file__).read_text(encoding="utf-8")
    environment = {"python": platform.python_version(), "ocp_package": OCP_VERSION,
                   "dependencies": {}}
    digest = hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest()
    return RecipePin(source, digest, entrypoint="build_scene", dependencies={})


def _box(bounds):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    (x0, y0, z0), (x1, y1, z1) = bounds
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def _shape(key, parameters):
    """The output's shape is built FROM INSTANCE PARAMETERS, not module constants.

    🔴 THIS IS NOT COSMETIC. "Fix = edit an authored parameter" requires the
    parameter to EXIST: each body's box lives in
    `instance.parameters[output_key]`, and `kir.project_fix.propose_fix`
    raises exactly that one, and then the same function rebuilds the body.
    Keep the coordinates only in the module, and a "fix" would become a FILE
    edit that no revision survives.
    """
    if key != "podium":
        return _box(parameters[key])
    from examples.residential_with_podium import build_podium_body

    return build_podium_body(dict(parameters["podium"]))


def _root():
    from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision

    seed = NamedOutput("origin", {"op": "create_level", "elev_mm": 0, "name": "L0"})
    return ProjectRevision(PROJECT_ID, [ModuleDefinition(MODULE)],
                           [ModuleInstance("origin", MODULE, [seed])])


def build_scene(*, frame=None, extra=()):
    """-> (ProjectRevision, {output_key: GeometryBundle}). Bodies are real, OCCT is real.

    `frame` — the frame of ALL instances (a rigid transform of the scene).
    The default is the identity, meaning the scene and its numbers do not
    shift by a single byte.
    🔴 WHY THE PARAMETER. A fix edits the box in the instance's PARAMETERS,
    i.e. in LOCAL coordinates, while it separates bodies in WORLD coordinates.
    With an identity frame this is the same number, and such a scene does not
    catch the defect at all. A rotation AROUND Z does not catch it either
    (local z coincides with world z) — that is why the pin rotates around a
    horizontal axis.
    `extra` — additional bodies `(key, (lo, hi))`: a neighbor that a lift may
    introduce the fixed body into.
    """
    from kir.occt_geometry import IDENTITY_FRAME, capture_body
    from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance,
                             NamedOutput, PROJECT_SCHEMA_V2)

    pin = _pin()
    parameters = dict(scene_parameters())
    for key, bounds in extra:
        parameters[key] = {key: [list(bounds[0]), list(bounds[1])]}
    placed = tuple(frame) if frame else IDENTITY_FRAME
    instances, bundles = [], {}
    for key, _bounds in (*BODIES, *extra):
        own = parameters[key]
        bundle = capture_body(_shape(key, own), project_id=PROJECT_ID,
                              instance_key=key, output_key=key, recipe=pin,
                              # Bundle parameters = the parameters of ITS instance, in full.
                              parameters=own, frame=placed, linear_deflection_mm=40.)
        bundles[key] = bundle
        output = NamedOutput(
            key, {"op": "create_directshape", "category": "mass", "name": "acceptance " + key},
            BodyRepresentation(bundle.digest, bundle.body_digest))
        instances.append(ModuleInstance(key, MODULE, [output], own,
                                        metadata={"scene": "podium-passage",
                                                  "bim_semantics": "absent",
                                                  "native_execution": "not_run"}))
    root = _root()
    upgraded = root.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=root.revision_id)
    revision = upgraded.revise(
        expected_revision=upgraded.revision_id,
        modules=[ModuleDefinition(MODULE, "sealed_evaluation", pin)], instances=instances)
    return revision, bundles


def save(path, *, frame=None, extra=()):
    """Store /1 -> explicit upgrade to /2 -> commit the revision TOGETHER with the bodies."""
    from kir.project_store import ProjectStore

    revision, bundles = build_scene(frame=frame, extra=extra)
    root = _root()
    store = ProjectStore.create(Path(path), root)
    store.upgrade_schema("kir-project-store/2", expected_revision=root.revision_id)
    upgraded = root.upgrade_schema(revision.schema, expected_revision=root.revision_id)
    store.commit(upgraded, expected_revision=root.revision_id)
    store.commit(revision, expected_revision=upgraded.revision_id, assets=list(bundles.values()))
    return store


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print(__doc__.strip())
        return 2
    target = Path(argv[0])
    if target.exists():
        print(f"отказ: файл уже существует — {target}")
        return 1
    store = save(target)
    head = store.head()
    bodies = [oid for _i, output, oid in head.addressed_outputs() if output.geometry is not None]
    print(f"сцена сохранена: {target}")
    print(f"  ревизия {head.revision_id}")
    print(f"  тел: {len(bodies)} ({', '.join(key for key, _ in BODIES)})")
    print("  анализ: python -c \"from kir.clash.project_analysis import analyze_project;"
          f" print(analyze_project('{target}').to_dict())\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
