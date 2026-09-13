"""Read-only descriptors for two disjoint sandbox recipe tasks in the saved apartment complex.

Reading source/parameters does not run the script, compile, materialize a body,
or modify a module. The coordinator explicitly prepares the two module keys
before assigning instance/module grants; the binder pins the observed run.
"""
from pathlib import Path

from kir.project import ProjectError, ProjectRevision


SECTION_MODULE = "agent-section-a"
TOWER_MODULE = "agent-tower-b"
_PARAMETERS = {"representation", "x_mm", "width_mm", "depth_mm", "storeys",
               "storey_height_mm", "terrace_setback_mm", "twist_deg"}
_CONTEXT = {"project_id", "instance_key", "project_ir_version", "project_intent"}


class ResidentialRecipeError(ProjectError):
    code = "residential_recipe_scope_mismatch"


def _descriptor(project, *, instance_key, module_key, representation, filename, keys, overrides):
    if type(project) is not ProjectRevision:
        raise ResidentialRecipeError("expected exact ProjectRevision")
    instance = next((item for item in project.instances if item.key == instance_key), None)
    definition = next((item for item in project.modules if item.key == module_key), None)
    if (instance is None or definition is None
            or any(item.key != instance_key and item.module_key == module_key for item in project.instances)):
        raise ResidentialRecipeError("target instance and dedicated preallocated module are required")
    parameters = dict(instance.parameters)
    if (not _PARAMETERS <= set(parameters) or set(parameters) - (_PARAMETERS | _CONTEXT)
            or parameters["representation"] != representation
            or tuple(output.key for output in instance.outputs) != keys
            or any(output.geometry is not None for output in instance.outputs)):
        raise ResidentialRecipeError("unsupported parameter/output scope; no existing inputs are discarded")
    if instance_key == "tower-a" and (type(parameters["storeys"]) is not int or parameters["storeys"] != 3):
        raise ResidentialRecipeError("this section recipe preserves exactly three storeys and 21 members")
    context = {"project_id": project.project_id, "instance_key": instance_key,
               "project_ir_version": project.ir_version, "project_intent": project.intent}
    if any(key in parameters and (type(parameters[key]) is not str or parameters[key] != value)
           for key, value in context.items()):
        raise ResidentialRecipeError("retained recipe context differs from this project/instance")
    parameters.update(overrides)
    parameters.update(context)
    return {"source": (Path(__file__).parent / "recipes" / filename).read_text(encoding="utf-8"),
            "instance_key": instance_key, "module_key": module_key,
            "output_keys": keys, "parameters": parameters}


def section_recipe(project, *, height_mm=4500., setback_mm=1200.):
    """Exact baseline inputs + two explicit edits; twist remains inactive."""
    keys = tuple(f"storey-{number:02d}-{suffix}" for number in range(1, 4)
                 for suffix in ("level", "slab", "wall-0", "wall-1", "wall-2", "wall-3", "space"))
    return _descriptor(project, instance_key="tower-a", module_key=SECTION_MODULE,
        representation="section", filename="residential_section.py", keys=keys,
        overrides={"storey_height_mm": height_mm, "terrace_setback_mm": setback_mm})


def tower_recipe(project, *, storeys=8, height_mm=4100., twist_deg=-24.):
    """Exact baseline inputs + storeys/height/twist edits of concept-volume."""
    return _descriptor(project, instance_key="tower-b", module_key=TOWER_MODULE,
        representation="concept", filename="residential_tower.py", keys=("concept-volume",),
        overrides={"storeys": storeys, "storey_height_mm": height_mm, "twist_deg": twist_deg})
