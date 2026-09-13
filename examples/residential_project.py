"""A saved concept, one developed section, and a later parametric change.

Run from a source checkout with PYTHONPATH set to that checkout:

    python examples/residential_project.py --stage changed

Stdout is ProjectRevision JSON. No Revit, network, files, or saved recipe code
are executed by loading that JSON. This script explicitly runs the Python
generator before sealing its outputs. It is an authoring example, not a
completed residential design, a native readback, or a general CAD kernel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import platform

from kir import sdk
from kir.project import (
    ModuleDefinition, ModuleInstance, ProjectError, ProjectRevision, RecipePin, output_id,
)


PROJECT_ID = "residential-foundation"
MODULE_KEY = "residential-module-v1"


def _ring(x: float, width: float, depth: float) -> list[list[float]]:
    return [[x, 0.0], [x + width, 0.0], [x + width, depth], [x, depth]]


def _region(points: list[list[float]]) -> dict:
    return {"outer": {"shape": "poly", "points_mm": points}}


def generate_outputs(project_id: str, instance_key: str, parameters: dict) -> dict:
    """Ordinary Python generates an ordered mapping of named SDK operations."""
    x = parameters["x_mm"]
    width = parameters["width_mm"]
    depth = parameters["depth_mm"]
    storeys = parameters["storeys"]
    height = parameters["storey_height_mm"]
    setback = parameters["terrace_setback_mm"]
    # 🔴 TERRACE STOREYS — AN ADDITION, NOT A BEHAVIOR CHANGE (07.09.2026, Q01).
    # Before this turn the setback was EXACTLY ONE and always at the top
    # floor (`setback if number == storeys else 0`), so there was nothing to
    # show a plural registry of "terraces" with: the end-to-end instrument
    # measured one outline of 14000 and one of 12200. The keys are OPTIONAL
    # and the defaults reproduce the previous number exactly:
    # `terrace_storeys=1`, step 0. Saved instances do not carry these keys,
    # their pins and all previous measurements (25 outputs, 21 section
    # outputs, 23 program ops) do not shift by a single byte.
    tiers = parameters.get("terrace_storeys", 1)
    step = parameters.get("terrace_setback_step_mm", 0)
    if (type(storeys) is not int or storeys < 1
            or type(tiers) is not int or not 1 <= tiers <= storeys
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in (x, width, depth, height, setback, step))
            or min(width, depth, height) <= 0 or not 0 <= setback < width / 2
            or step < 0 or step * (tiers - 1) > setback):
        raise ValueError("invalid residential dimensions")

    footprint = _ring(x, width, depth)
    if parameters["representation"] == "concept":
        angle = math.radians(parameters["twist_deg"])
        cx, cy = x + width / 2, depth / 2
        top = [[cx + 0.82 * ((px - cx) * math.cos(angle)
                            - (py - cy) * math.sin(angle)),
                cy + 0.82 * ((px - cx) * math.sin(angle)
                            + (py - cy) * math.cos(angle))]
               for px, py in footprint]
        return {"concept-volume": sdk.create_solid_blend(
            profile=_region(footprint), profile_top=_region(top),
            height_mm=storeys * height, base_z_mm=0,
            category="mass", name=instance_key)}
    if parameters["representation"] != "section":
        raise ValueError("representation must be concept or section")
    # This example has a fixed 2 x 2 m shaft. It is not a generic floor-layout
    # solver: reject dimensions that put the hole outside even the terrace floor.
    if width - setback <= 7000 or depth <= 5000:
        raise ValueError("shaft must be strictly inside every section floor")

    def _setback_of(number: int) -> float:
        """Setback of THIS floor: the top tier is full, each one below is smaller by a step."""
        tier = storeys - number
        return setback - step * tier if tier < tiers else 0

    outputs = {}
    for number in range(1, storeys + 1):
        prefix = f"storey-{number:02d}"
        level_key = f"{prefix}-level"
        level_ref = sdk.ref(output_id(project_id, instance_key, level_key))
        outputs[level_key] = sdk.create_level(
            elev_mm=(number - 1) * height, name=f"{instance_key}: этаж {number}")
        current_width = width - _setback_of(number)
        contour = _region(_ring(x, current_width, depth))
        contour["holes"] = [{"shape": "poly", "points_mm": [
            [x + 5000, 3000], [x + 7000, 3000],
            [x + 7000, 5000], [x + 5000, 5000],
        ]}]
        outputs[f"{prefix}-slab"] = sdk.create_floor_by_contour(
            contour=contour, level=level_ref)
        corners = _ring(x, current_width, depth)
        for side, (start, end) in enumerate(zip(corners, corners[1:] + corners[:1])):
            outputs[f"{prefix}-wall-{side}"] = sdk.create_wall(
                p0_mm=start, p1_mm=end, height_mm=height, level=level_ref)
        outputs[f"{prefix}-space"] = sdk.create_room(
            xy=[x + 2500, 2000], name=f"{instance_key}: пространство {number}",
            level=level_ref)
    return outputs


_ROLE_BY_OP = {"create_level": "level", "create_floor_by_contour": "slab",
               "create_wall": "wall", "create_room": "space"}


def instance(key: str, parameters: dict, *, project_id: str = PROJECT_ID,
             refines: tuple[str, ...] = ()) -> ModuleInstance:
    """Run the generator explicitly, then retain its complete asserted result."""
    metadata = {"refines": list(refines), "development": "draft",
                "native_realization": "unverified"}
    # 🔴 THE LOOSE `refinement` RECORD WAS REMOVED 07.09.2026. It declared
    # lineage with FOUR fields — with no schema, no source, and no members —
    # and the typed view rejected it by name (`legacy_unbound_refinement`).
    # That is, there were two carriers of one fact: one readable, the other
    # not. Two carriers are bound to diverge; here they diverged SILENTLY,
    # and "agreed details" were lost on every repeated call of the generator.
    # Lineage is now written by exactly one place — `kir.project_refinement`
    # — and it writes it as a typed record. The generator does NOT declare
    # the shape.
    return ModuleInstance(
        key, MODULE_KEY, generate_outputs(project_id, key, parameters), parameters,
        metadata=metadata,
    )


def _recipe() -> RecipePin:
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    sdk_digest = hashlib.sha256(pathlib.Path(sdk.__file__).read_bytes()).hexdigest()
    declared_environment = {"python": platform.python_version(), "sdk": sdk_digest}
    environment_digest = hashlib.sha256(json.dumps(
        declared_environment, sort_keys=True).encode("utf-8")).hexdigest()
    # This is deliberately a declared pin, not a complete environment lock or
    # evidence that re-execution by an arbitrary future interpreter will match.
    return RecipePin(source, environment_digest, entrypoint="generate_outputs",
                     dependencies={"kir.sdk": sdk_digest})


def concept() -> ProjectRevision:
    instances = []
    for index, (key, floors, twist) in enumerate((
        ("tower-a", 3, 12), ("tower-b", 5, -9), ("tower-c", 7, 18),
    )):
        instances.append(instance(key, {
            "representation": "concept", "x_mm": index * 24000,
            "width_mm": 14000, "depth_mm": 9000, "storeys": floors,
            "storey_height_mm": 3600, "terrace_setback_mm": 900,
            "twist_deg": twist,
        }))
    return ProjectRevision(
        PROJECT_ID, (ModuleDefinition(MODULE_KEY, "sealed_evaluation", _recipe()),),
        instances, intent="Три концептуальных объёма; одна секция развивается отдельно",
        metadata={"operation_units": "mm", "operation_frame": "project-local",
                  "limitations": ["not a complete BIM design", "no live readback"]},
    )


def develop_section(project: ProjectRevision, *, height_mm: float = 3600,
                    setback_mm: float = 900) -> ProjectRevision:
    previous = next(item for item in project.instances if item.key == "tower-a")
    definition = next(item for item in project.modules if item.key == previous.module_key)
    current = ModuleDefinition(MODULE_KEY, "sealed_evaluation", _recipe())
    if definition.definition_digest != current.definition_digest:
        raise ProjectError(
            "saved generator definition differs from the current example; "
            "explicit source/environment migration is required before regeneration")
    parameters = dict(previous.parameters)
    parameters.update(representation="section", storey_height_mm=height_mm,
                      terrace_setback_mm=setback_mm)
    refines = tuple(previous.metadata["refines"])
    if previous.parameters["representation"] == "concept":
        refines = (output_id(project.project_id, previous.key, "concept-volume"),)
    replacement = instance(previous.key, parameters, project_id=project.project_id,
                           refines=refines)
    return project.replace_instance(replacement, expected_revision=project.revision_id)


def workflow() -> tuple[ProjectRevision, ProjectRevision, ProjectRevision]:
    initial = concept()
    developed = develop_section(initial)
    # The next change starts from the persisted value, not the generator's
    # current Python objects. Other towers and the prior refinement lineage stay.
    resumed = ProjectRevision.loads(developed.dumps())
    changed = develop_section(resumed, height_mm=4200, setback_mm=1800)
    return initial, developed, changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("concept", "refined", "changed"),
                        default="changed")
    parser.add_argument("--store", metavar="NEW_DATABASE",
                        help="save the complete history up to this stage in a new SQLite file")
    args = parser.parse_args(argv)
    stages = dict(zip(("concept", "refined", "changed"), workflow()))
    selected = stages[args.stage]
    selected.plan()
    if args.store is not None:
        from kir.project_store import ProjectStore, ProjectStoreError

        try:
            store = ProjectStore.create(args.store, stages["concept"])
            for stage, revision in stages.items():
                if stage != "concept":
                    store.commit(revision, expected_revision=revision.parent_revision)
                if stage == args.stage:
                    break
        except ProjectStoreError as exc:
            parser.exit(2, f"history not completed: {exc}\n"
                        "A saved prefix may exist; inspect its head before continuing.\n")
    print(selected.dumps())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
