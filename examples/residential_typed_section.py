"""Explicit layered types for the saved three-storey schematic section.

The new host generator has its OWN declared source/dependency pin. Existing
recipes are never relabelled or executed from stored text. A separate explicit
type-library instance precedes tower-a; its layers/names are authored choices,
while its source selectors are caller-supplied Revit dependencies, not observed
identities. Native template properties outside CompoundStructure remain partly
inherited. Planning this example does not prove geometry or native readiness.
Repeated native publication is not an update strategy: the changed whole-plan
stamp needs explicit type binding/reconciliation, not automatic type renaming.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform

from examples import residential_project as original
from kir import sdk
from kir.compiler import KirRefusal, plan_program
from kir.project import (ModuleDefinition, ModuleInstance, NamedOutput, ProjectError,
                         ProjectRevision, RecipePin, _canonical, _digest, _object, _thaw, output_id)
from kir.project_refinement import (adopt_foreign_members, carry_schematic_refinement,
                                    refinement_view)
from kir.project_selection import selected_instance_program
from kir.project_store import ProjectStore, StoreConflict


TYPE_INSTANCE = "section-types"
TYPE_MODULE = "residential-section-types"
SECTION_MODULE = "residential-typed-section-v1"
WALL_TYPE_OUTPUT = "exterior-wall-type"
FLOOR_TYPE_OUTPUT = "floor-type"
_INPUT_KEYS = {"representation", "x_mm", "width_mm", "depth_mm", "storeys",
               "storey_height_mm", "terrace_setback_mm", "twist_deg"}
_CONTEXT_KEYS = {"project_id", "instance_key", "project_ir_version", "project_intent"}
_TYPE_INPUTS = {"wall_type_output_id", "floor_type_output_id"}


class TypedSectionError(ProjectError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def recipe_pin():
    """Declared host environment/dependencies, not sandbox execution evidence."""
    source = Path(__file__).read_text(encoding="utf-8")
    dependencies = {"examples.residential_project": hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest(),
                    "kir.sdk": hashlib.sha256(Path(sdk.__file__).read_bytes()).hexdigest()}
    environment = {"python": platform.python_version(), "dependencies": dependencies}
    return RecipePin(source, hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest(),
                     entrypoint="generate_outputs", dependencies=dependencies)


def _require(condition, code, message):
    if not condition:
        raise TypedSectionError(code, message)


def _section(project, source, expected_revision):
    _require(type(project) is ProjectRevision and type(source) is ProjectRevision,
             "invalid_typed_section", "exact project and historical refinement source are required")
    project._check_revision(expected_revision)
    refinement_view(project, "tower-a", source=source)
    instance = next(item for item in project.instances if item.key == "tower-a")
    values = _thaw(instance.parameters)
    _require(_INPUT_KEYS <= set(values) and not set(values) - (_INPUT_KEYS | _CONTEXT_KEYS | _TYPE_INPUTS)
             and values["representation"] == "section" and type(values["storeys"]) is int and values["storeys"] == 3,
             "unsupported_section_snapshot", "only the complete three-storey example inputs are interpreted")
    context = {"project_id": project.project_id, "instance_key": instance.key,
               "project_ir_version": project.ir_version, "project_intent": project.intent}
    _require(all(key not in values or type(values[key]) is str and values[key] == value for key, value in context.items()),
             "unsupported_section_snapshot", "retained recipe namespace differs from this project")
    return instance


def _exact_outputs(instance, expected):
    actual = [output.to_dict() for output in instance.outputs]
    wanted = [NamedOutput(key, operation).to_dict() for key, operation in expected.items()]
    _require(_canonical(actual) == _canonical(wanted), "unsupported_section_snapshot",
             "existing outputs differ from the supported generator; custom fields/geometry are not discarded")


def _seed(value):
    selector = _thaw(_object(value, "backend_seed_selector"))
    _require(set(selector) == {"by", "value"} and selector.get("by") in ("name", "element_id"),
             "unsupported_backend_seed", "supply an explicit name or element_id selector; no default or generated seed is guessed")
    return selector  # Existing compiler owns selector value/type/bounds validation.


def _type_outputs(project, wall_name, wall_layers, wall_source_type, floor_name, floor_layers, floor_source_type):
    seeds = {"wall": _seed(wall_source_type), "floor": _seed(floor_source_type)}
    values = {WALL_TYPE_OUTPUT: {"op": "create_wall_type", "host_kind": "wall", "new_name": wall_name,
                                "layers": wall_layers, "source_type": seeds["wall"]},
              FLOOR_TYPE_OUTPUT: {"op": "create_wall_type", "host_kind": "floor", "new_name": floor_name,
                                 "layers": floor_layers, "source_type": seeds["floor"]}}
    outputs = tuple(NamedOutput(key, value) for key, value in values.items())
    _plan({"ir_version": project.ir_version, "intent": project.intent,
           "ops": [{**output.to_dict()["operation"], "id": output_id(project.project_id, TYPE_INSTANCE, output.key)}
                   for output in outputs]})
    return outputs, seeds


def _plan(program):
    try:
        return plan_program(program)
    except KirRefusal as error:
        raise TypedSectionError("typed_section_plan_refused", "existing compiler rejected the authored types/section") from error


def generate_outputs(project_id, instance_key, parameters):
    """Explicitly run unchanged geometry generator, then attach declared refs."""
    outputs = original.generate_outputs(project_id, instance_key, parameters)
    for operation in outputs.values():
        if operation["op"] == "create_wall":
            operation["type"] = {"by": "ref", "value": parameters["wall_type_output_id"]}
        elif operation["op"] == "create_floor_by_contour":
            operation["type"] = {"by": "ref", "value": parameters["floor_type_output_id"]}
    return outputs


def _type_ids(project):
    return {"wall_type_output_id": output_id(project.project_id, TYPE_INSTANCE, WALL_TYPE_OUTPUT),
            "floor_type_output_id": output_id(project.project_id, TYPE_INSTANCE, FLOOR_TYPE_OUTPUT)}


def _library(project):
    index = {item.key: position for position, item in enumerate(project.instances)}
    _require(TYPE_INSTANCE in index and index[TYPE_INSTANCE] < index["tower-a"],
             "type_library_mismatch", "type-library instance must precede its consumers")
    library = project.instances[index[TYPE_INSTANCE]]
    definition = next(item for item in project.modules if item.key == library.module_key)
    _require(definition == ModuleDefinition(TYPE_MODULE) and library.module_key == TYPE_MODULE
             and tuple(output.key for output in library.outputs) == (WALL_TYPE_OUTPUT, FLOOR_TYPE_OUTPUT)
             and set(library.parameters) == {"backend_seed_selectors"},
             "type_library_mismatch", "expected the dedicated explicit two-type library")
    seeds = _thaw(library.parameters["backend_seed_selectors"])
    _require(type(seeds) is dict and set(seeds) == {"wall", "floor"},
             "type_library_mismatch", "backend seed input declaration is malformed")
    for kind, output in zip(("wall", "floor"), library.outputs, strict=True):
        operation = _thaw(output.operation)
        _require(output.geometry is None and operation.get("op") == "create_wall_type"
                 and operation.get("host_kind") == kind and _canonical(operation.get("source_type")) == _canonical(seeds[kind]),
                 "type_library_mismatch", "type output and its separate backend seed input differ")
        _seed(seeds[kind])
    _plan(selected_instance_program(project, TYPE_INSTANCE))
    return library


def add_section_types(project, *, source, expected_revision, wall_name, wall_layers, wall_source_type,
                      floor_name, floor_layers, floor_source_type):
    """One unsaved direct child; all seeds and layer/name inputs are explicit."""
    previous = _section(project, source, expected_revision)
    _require(not any(item.key in (TYPE_MODULE, SECTION_MODULE) for item in project.modules)
             and not any(item.key == TYPE_INSTANCE for item in project.instances),
             "typed_section_key_collision", "new type/section module and instance keys must not already exist")
    _require(not (_TYPE_INPUTS & set(previous.parameters)), "unsupported_section_snapshot", "section already declares type bindings")
    _exact_outputs(previous, original.generate_outputs(project.project_id, previous.key, _thaw(previous.parameters)))
    outputs, seeds = _type_outputs(project, wall_name, wall_layers, wall_source_type, floor_name, floor_layers, floor_source_type)
    library = ModuleInstance(TYPE_INSTANCE, TYPE_MODULE, outputs, {"backend_seed_selectors": seeds},
        metadata={"role": "explicit_layered_type_library", "backend_seed_identity": "not_verified",
                  "inherited_type_properties": "not_fully_specified", "native_execution": "not_run"})
    definition = ModuleDefinition(SECTION_MODULE, "sealed_evaluation", recipe_pin())
    parameters = {**_thaw(previous.parameters), **_type_ids(project)}
    replacement = replace(previous, module_key=definition.key, module_digest=definition.definition_digest,
                          parameters=parameters, outputs=generate_outputs(project.project_id, previous.key, parameters))
    items = []
    for instance in project.instances:
        items.extend((library, replacement) if instance.key == previous.key else (instance,))
    # 🔴 TYPES ARE BROUGHT UNDER LINEAGE HERE, NOT "SOMEDAY". They are born
    # in exactly this turn and live in a SEPARATE instance; not naming them
    # as members would mean leaving two of the section program's twenty-three
    # outputs without an address — an instrumentally measurable hole, not a
    # cosmetic detail.
    #
    # Adoption is done BEFORE `revise`, in one snapshot: a second revision
    # would take the proposal away from its direct parent, and the store
    # would refuse on `expected_revision` (measured: this is exactly what
    # happened while the turn was second). Membership of foreign members will
    # be checked by `refinement_view` below — already on the finished
    # revision, where these outputs exist.
    replacement = adopt_foreign_members(replacement, None,
        members=[{"instance_key": TYPE_INSTANCE, "output_key": output.key, "role": "wall_type"}
                 for output in outputs],
        part_id="section_types")
    items = []
    for instance in project.instances:
        items.extend((library, replacement) if instance.key == previous.key else (instance,))
    candidate = project.revise(expected_revision=expected_revision,
        modules=(*project.modules, ModuleDefinition(TYPE_MODULE), definition), instances=items)
    _library(candidate)
    _plan(selected_instance_program(candidate, previous.key))
    refinement_view(candidate, previous.key, source=source)
    return candidate


def edit_section(project, *, source, expected_revision, height_mm, setback_mm):
    """Continue the exact new host recipe; type-library snapshots are untouched."""
    previous = _section(project, source, expected_revision)
    definition = next(item for item in project.modules if item.key == previous.module_key)
    expected_definition = ModuleDefinition(SECTION_MODULE, "sealed_evaluation", recipe_pin())
    _require(definition == expected_definition, "typed_section_recipe_changed",
             "saved host source/dependency pin differs; explicit migration is required before generation")
    _library(project)
    expected_ids = _type_ids(project)
    _require(all(previous.parameters.get(key) == value for key, value in expected_ids.items()),
             "type_library_mismatch", "section input references another type library")
    _exact_outputs(previous, generate_outputs(project.project_id, previous.key, _thaw(previous.parameters)))
    parameters = {**_thaw(previous.parameters), "storey_height_mm": height_mm, "terrace_setback_mm": setback_mm}
    replacement = replace(previous, parameters=parameters, outputs=generate_outputs(project.project_id, previous.key, parameters))
    replacement = carry_schematic_refinement(previous, replacement)
    candidate = project.replace_instance(replacement, expected_revision=expected_revision)
    _plan(selected_instance_program(candidate, previous.key))
    refinement_view(candidate, previous.key, source=source)
    return candidate


def continue_section(store: ProjectStore, *, expected_revision, height_mm, setback_mm):
    """Explicit generator call + existing ProjectStore head CAS; no native work."""
    _require(type(store) is ProjectStore, "invalid_typed_section", "expected an exact ProjectStore")
    previous = store.head()
    if previous.revision_id != expected_revision:
        raise StoreConflict("typed section edit requires the expected authored head")
    section = next((item for item in previous.instances if item.key == "tower-a"), None)
    _require(section is not None, "source_snapshot_required", "saved project has no tower-a section")
    try:
        source_id = _digest(section.metadata["refinement"]["source"]["revision_id"], "source.revision_id")
    except (KeyError, TypeError, ProjectError) as error:
        raise TypedSectionError("source_snapshot_required", "section requires its exact historical refinement source") from error
    source = store.get(source_id)
    candidate = edit_section(previous, source=source, expected_revision=expected_revision,
                             height_mm=height_mm, setback_mm=setback_mm)
    store.commit(candidate, expected_revision=expected_revision)
    return candidate
