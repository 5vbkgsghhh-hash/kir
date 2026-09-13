"""A small, persistent authoring project above the existing operation compiler.

This is a regenerate-first carrier, not an interpreter or a graph database.
Definitions name ownership; instances own their complete evaluated snapshots.
An explicit instance contains authored operations. A sealed-evaluation instance
contains an *asserted* result and its parameters, optionally linked to inert
recipe source. A digest does not prove that source produced those operations.
Changing a sealed instance replaces the whole snapshot, not just its parameters.

Named outputs identify top-level operations, not necessarily individual BIM
elements: an operation may produce many elements or expand a macro. IDs survive
unrelated insertion/reordering, but native bindings and expanded children have
their own contracts. References must already use :func:`output_id`; this module
never rewrites arbitrary dictionaries or guesses an execution order.

All operation numbers remain in the existing KIR units and coordinate system.
Project/instance metadata (including a declared frame or units of a recipe
input) is preserved but is NOT an instruction to transform operation geometry.
``to_program`` only lowers; ``plan`` invokes the actual semantic validator.

The JSON hash detects accidental changes, not malicious authorship. There is no
signature, file lock, database CAS, code execution, import, or network access.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from collections.abc import Mapping, Sequence
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from kir.midend import PlannedProgram


PROJECT_SCHEMA = "kir-authoring-project/1"
PROJECT_SCHEMA_V2 = "kir-authoring-project/2"
_KEY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class ProjectError(ValueError):
    """An authoring project is malformed or its integrity does not match."""


class RevisionConflict(ProjectError):
    """A caller proposed a change against a different immutable revision."""


class GeometryResolutionRequired(ProjectError):
    """A body-owned output cannot use a cached preview as compiled geometry."""

    code = "geometry_resolution_required"


def _key(value: Any, name: str) -> str:
    if (not isinstance(value, str) or not _KEY.fullmatch(value)
            or ".." in value):
        raise ProjectError(
            f"{name}: expected a stable ASCII key (1–128 letters/digits/_.-, "
            "no '..'); use metadata for display names")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ProjectError(f"{name}: expected a lowercase SHA-256 hex digest")
    return value


def _freeze(value: Any, path: str = "value") -> Any:
    """Copy JSON data without coercing keys, numbers, or scalar types."""
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ProjectError(f"{path}: invalid Unicode") from exc
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ProjectError(f"{path}: non-finite numbers are not JSON")
        return value
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProjectError(f"{path}: JSON object keys must be strings")
            _freeze(key, path)
            frozen[key] = _freeze(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item, f"{path}[{i}]")
                     for i, item in enumerate(value))
    raise ProjectError(f"{path}: {type(value).__name__} is not JSON data")


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectError(f"{path}: expected a JSON object")
    try:
        return _freeze(value, path)
    except RecursionError as exc:
        raise ProjectError(f"{path}: cyclic or excessively nested JSON data") from exc


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _canonical(value: Any) -> str:
    # Same encoding convention as the mid-end; strict JSON types are checked
    # here as well, since json.dumps alone silently stringifies integer keys.
    try:
        return json.dumps(_thaw(_freeze(value)), ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProjectError(f"project is not canonical JSON: {exc}") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _fields(value: Any, names: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectError(f"{path}: expected a JSON object")
    if set(value) != names:
        raise ProjectError(
            f"{path}: unexpected/missing fields; expected {sorted(names)}")
    return value


def _array(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise ProjectError(f"{path}: expected a JSON array")
    return value


def _current_ir_version() -> str:
    from kir.registry_base import IR_VERSION

    return IR_VERSION


def output_id(project_id: str, instance_key: str, output_key: str) -> str:
    """A compiler-safe operation ID independent of position and content.

    The full SHA-256 is namespaced by the project, instance and output keys.
    Renaming any key intentionally changes identity. This is not a Revit ID.
    """
    keys = [_key(project_id, "project_id"), _key(instance_key, "instance_key"),
            _key(output_key, "output_key")]
    # The existing compiler permits at most 64 characters. Namespace the hash
    # input rather than adding a textual prefix that would exceed that bound.
    return _hash(["kir-project-output/1", *keys])


@dataclass(frozen=True, slots=True)
class RecipePin:
    """Inert source/provenance; never executed by loading or lowering.

    ``environment_digest`` and dependency digests are declarations supplied by
    the caller (for example the sandbox's environment signature). Their mere
    presence is not a verified replay or a complete reproducible environment.
    """

    source: str
    environment_digest: str
    entrypoint: str = "build"
    dependencies: Mapping[str, str] = field(default_factory=dict)
    source_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source:
            raise ProjectError("recipe.source: expected nonempty inert source text")
        _freeze(self.source, "recipe.source")
        _digest(self.environment_digest, "recipe.environment_digest")
        _key(self.entrypoint, "recipe.entrypoint")
        dependencies = _object(self.dependencies, "recipe.dependencies")
        for name, digest in dependencies.items():
            if not name:
                raise ProjectError("recipe.dependencies: empty dependency name")
            _digest(digest, f"recipe.dependencies.{name}")
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "source_digest", hashlib.sha256(
            self.source.encode("utf-8")).hexdigest())

    def to_dict(self) -> dict:
        return {"source": self.source, "source_digest": self.source_digest,
                "environment_digest": self.environment_digest,
                "entrypoint": self.entrypoint,
                "dependencies": _thaw(self.dependencies)}

    @classmethod
    def from_dict(cls, value: Any) -> RecipePin:
        data = _fields(value, {"source", "source_digest", "environment_digest",
                               "entrypoint", "dependencies"}, "recipe")
        pin = cls(data["source"], data["environment_digest"], data["entrypoint"],
                  data["dependencies"])
        if data["source_digest"] != pin.source_digest:
            raise ProjectError("recipe.source_digest: integrity mismatch")
        return pin


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    """Definition of ownership, not a second mutable copy of instance bodies.

    A sealed result may have unknown provenance (``recipe=None``). An explicit
    body cannot claim recipe ownership at the same time.
    """

    key: str
    owner: str = "explicit"
    recipe: RecipePin | None = None

    def __post_init__(self) -> None:
        _key(self.key, "module.key")
        if self.owner not in ("explicit", "sealed_evaluation"):
            raise ProjectError("module.owner: expected explicit or sealed_evaluation")
        if self.recipe is not None and not isinstance(self.recipe, RecipePin):
            raise ProjectError("module.recipe: expected RecipePin or None")
        if self.owner == "explicit" and self.recipe is not None:
            raise ProjectError("explicit module cannot also be owned by a recipe")

    def to_dict(self) -> dict:
        return {"key": self.key, "owner": self.owner,
                "recipe": self.recipe.to_dict() if self.recipe else None}

    @property
    def definition_digest(self) -> str:
        """Identity of the exact declared owner/provenance, not an output ID."""
        return _hash(self.to_dict())

    @classmethod
    def from_dict(cls, value: Any) -> ModuleDefinition:
        data = _fields(value, {"key", "owner", "recipe"}, "module")
        recipe = (RecipePin.from_dict(data["recipe"])
                  if data["recipe"] is not None else None)
        return cls(data["key"], data["owner"], recipe)


@dataclass(frozen=True, slots=True)
class BodyRepresentation:
    """Inert reference to the geometry owner, not a claim about cached meshes.

    The pinned bundle owns body bytes, mm/frame and requested tessellation.
    Loading this descriptor neither requires the asset nor imports a kernel.
    """

    bundle_sha256: str
    body_sha256: str

    def __post_init__(self) -> None:
        _digest(self.bundle_sha256, "geometry.bundle_sha256")
        _digest(self.body_sha256, "geometry.body_sha256")

    def to_dict(self) -> dict:
        return {"kind": "occt_brep_mesh", "bundle_sha256": self.bundle_sha256,
                "body_sha256": self.body_sha256}

    @classmethod
    def from_dict(cls, value: Any) -> BodyRepresentation:
        data = _fields(value, {"kind", "bundle_sha256", "body_sha256"}, "geometry")
        if data["kind"] != "occt_brep_mesh":
            raise ProjectError("unsupported body representation kind")
        return cls(data["bundle_sha256"], data["body_sha256"])


@dataclass(frozen=True, slots=True)
class NamedOutput:
    """One named top-level operation; its ID is supplied only by lowering."""

    key: str
    operation: Mapping[str, Any]
    geometry: BodyRepresentation | None = None

    def __post_init__(self) -> None:
        _key(self.key, "output.key")
        operation = _object(self.operation, f"output.{self.key}.operation")
        if "id" in operation:
            raise ProjectError("named output operation must not contain its own id")
        if not isinstance(operation.get("op"), str) or not operation["op"]:
            raise ProjectError("named output operation requires an op name")
        if self.geometry is not None:
            if not isinstance(self.geometry, BodyRepresentation):
                raise ProjectError("output.geometry must be a typed BodyRepresentation")
            if (operation["op"] != "create_directshape"
                    or set(operation) - {"op", "category", "name"}):
                raise ProjectError(
                    "body-owned output requires a DirectShape template with only "
                    "op/category/name; mesh is derived, never a second geometry owner")
        object.__setattr__(self, "operation", operation)

    def to_dict(self) -> dict:
        data = {"key": self.key, "operation": _thaw(self.operation)}
        if self.geometry is not None:
            data["geometry"] = self.geometry.to_dict()
        return data

    @classmethod
    def from_dict(cls, value: Any) -> NamedOutput:
        names = {"key", "operation"}
        if isinstance(value, Mapping) and "geometry" in value:
            names.add("geometry")
        data = _fields(value, names, "output")
        geometry = BodyRepresentation.from_dict(data["geometry"]) if "geometry" in data else None
        return cls(data["key"], data["operation"], geometry)


@dataclass(frozen=True, slots=True)
class ModuleInstance:
    """A whole authored/evaluated snapshot with an explicit operation order.

    The constructor accepts an insertion-ordered mapping of output keys to
    operations, or a sequence of NamedOutput. Internally and in JSON it becomes
    an ordered sequence: canonical object-key sorting cannot reorder effects.
    Parameters are retained inputs, not live bindings. Nothing regenerates an
    output when a parameter changes; replace this complete snapshot instead.
    A new instance may omit module_digest; its first ProjectRevision copies it
    with the exact definition pin. Already bound or persisted instances cannot
    silently acquire different recipe source or ownership in a later revision.
    """

    key: str
    module_key: str
    outputs: Mapping[str, Mapping[str, Any]] | Sequence[NamedOutput]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    module_digest: str | None = None

    def __post_init__(self) -> None:
        _key(self.key, "instance.key")
        _key(self.module_key, "instance.module_key")
        if self.module_digest is not None:
            _digest(self.module_digest, "instance.module_digest")
        if isinstance(self.outputs, Mapping):
            outputs = tuple(NamedOutput(key, op) for key, op in self.outputs.items())
        elif isinstance(self.outputs, (list, tuple)):
            outputs = tuple(self.outputs)
        else:
            raise ProjectError("instance.outputs: expected a mapping or output sequence")
        seen = set()
        for output in outputs:
            if not isinstance(output, NamedOutput):
                raise ProjectError("instance.outputs: expected NamedOutput entries")
            if output.key in seen:
                raise ProjectError(f"duplicate output key: {output.key}")
            seen.add(output.key)
        object.__setattr__(self, "outputs", outputs)
        object.__setattr__(self, "parameters", _object(self.parameters, "parameters"))
        object.__setattr__(self, "metadata", _object(self.metadata, "metadata"))

    def to_dict(self) -> dict:
        return {"key": self.key, "module_key": self.module_key,
                "outputs": [output.to_dict() for output in self.outputs],
                "parameters": _thaw(self.parameters), "metadata": _thaw(self.metadata),
                "module_digest": self.module_digest}

    @classmethod
    def from_dict(cls, value: Any) -> ModuleInstance:
        data = _fields(value, {"key", "module_key", "outputs", "parameters", "metadata",
                               "module_digest"},
                       "instance")
        # Persisted snapshots are always pinned. An unbound constructor value
        # is a new assertion; a loaded old snapshot cannot silently rebind.
        _digest(data["module_digest"], "instance.module_digest")
        outputs = tuple(NamedOutput.from_dict(item)
                        for item in _array(data["outputs"], "instance.outputs"))
        return cls(data["key"], data["module_key"], outputs,
                   data["parameters"], data["metadata"], data["module_digest"])


@dataclass(frozen=True, slots=True)
class ProjectRevision:
    """Immutable authoring revision; persistence is canonical JSON only.

    Expected-revision checks protect a change to *this value*. They are not an
    atomic compare-and-swap of a shared file, database, or another process.
    Operations may remain unplannable drafts; call ``plan`` before exporting a
    program as validated. Modules requiring separate programs (e.g. solo ops)
    are refused by that compiler rather than silently split into transactions.
    """

    project_id: str
    modules: Sequence[ModuleDefinition]
    instances: Sequence[ModuleInstance]
    intent: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    parent_revision: str | None = None
    ir_version: str = field(default_factory=_current_ir_version)
    schema: str = PROJECT_SCHEMA
    revision_id: str = field(init=False)
    #: THIS snapshot's own memory of its outputs' addresses. The
    #: snapshot is immutable (`frozen=True`), so `addressed_outputs()` is
    #: a pure function of it, and a second answer must match the first.
    #: Measured 07.09.2026 (2000 bodies, a head analysis): one pass costs
    #: 2000 `output_id` = 2000 SHA-256 over the canonicalized key, and
    #: there were ELEVEN passes over the course of the analysis — 22 000
    #: calls to `_hash` and 12.5 s of profile time. This field does not
    #: enter into the comparison, the hash, or the payload.
    _addressed: tuple | None = field(init=False, default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        _key(self.project_id, "project_id")
        if self.schema not in (PROJECT_SCHEMA, PROJECT_SCHEMA_V2):
            raise ProjectError(f"unsupported project schema: {self.schema!r}")
        if not isinstance(self.intent, str):
            raise ProjectError("intent: expected a string")
        _freeze(self.intent, "intent")
        if not isinstance(self.ir_version, str) or not self.ir_version:
            raise ProjectError("ir_version: expected a nonempty version string")
        _freeze(self.ir_version, "ir_version")
        if self.parent_revision is not None:
            _digest(self.parent_revision, "parent_revision")
        if not isinstance(self.modules, (list, tuple)):
            raise ProjectError("modules: expected a module sequence")
        if not isinstance(self.instances, (list, tuple)):
            raise ProjectError("instances: expected an instance sequence")
        modules, instances = tuple(self.modules), tuple(self.instances)
        module_digests = {}
        for module in modules:
            if not isinstance(module, ModuleDefinition):
                raise ProjectError("modules: expected ModuleDefinition entries")
            if module.key in module_digests:
                raise ProjectError(f"duplicate module key: {module.key}")
            module_digests[module.key] = module.definition_digest
        instance_keys = set()
        bound_instances = []
        for instance in instances:
            if not isinstance(instance, ModuleInstance):
                raise ProjectError("instances: expected ModuleInstance entries")
            if instance.key in instance_keys:
                raise ProjectError(f"duplicate instance key: {instance.key}")
            if instance.module_key not in module_digests:
                raise ProjectError(f"unknown module: {instance.module_key}")
            actual_digest = module_digests[instance.module_key]
            if instance.module_digest is None:
                instance = replace(instance, module_digest=actual_digest)
            elif instance.module_digest != actual_digest:
                raise ProjectError(
                    f"instance {instance.key}: module digest mismatch; replace the "
                    "whole evaluated snapshot for the new definition")
            bound_instances.append(instance)
            instance_keys.add(instance.key)
        if self.schema == PROJECT_SCHEMA and any(
                output.geometry is not None for instance in bound_instances for output in instance.outputs):
            raise ProjectError("body-owned outputs require an explicit upgrade to kir-authoring-project/2")
        object.__setattr__(self, "modules", modules)
        object.__setattr__(self, "instances", tuple(bound_instances))
        object.__setattr__(self, "metadata", _object(self.metadata, "metadata"))
        object.__setattr__(self, "revision_id", _hash(self._body()))

    def _body(self) -> dict:
        return {"schema": self.schema, "project_id": self.project_id,
                "ir_version": self.ir_version,
                "parent_revision": self.parent_revision, "intent": self.intent,
                "metadata": _thaw(self.metadata),
                "modules": [module.to_dict() for module in self.modules],
                "instances": [instance.to_dict() for instance in self.instances]}

    def to_dict(self) -> dict:
        """Detached JSON data; mutating it cannot change this revision."""
        return {**self._body(), "revision_id": self.revision_id}

    def dumps(self) -> str:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: Any) -> ProjectRevision:
        data = _fields(value, {"schema", "project_id", "parent_revision", "intent",
                               "metadata", "modules", "instances", "revision_id", "ir_version"},
                       "project")
        if data["schema"] not in (PROJECT_SCHEMA, PROJECT_SCHEMA_V2):
            raise ProjectError(f"unsupported project schema: {data['schema']!r}")
        expected = _digest(data["revision_id"], "revision_id")
        modules = tuple(ModuleDefinition.from_dict(item)
                        for item in _array(data["modules"], "modules"))
        instances = tuple(ModuleInstance.from_dict(item)
                          for item in _array(data["instances"], "instances"))
        project = cls(data["project_id"], modules, instances, data["intent"],
                      data["metadata"], data["parent_revision"], data["ir_version"], data["schema"])
        if expected != project.revision_id:
            raise ProjectError("project revision_id: integrity mismatch")
        return project

    @classmethod
    def loads(cls, source: str) -> ProjectRevision:
        """Strict JSON load, rejecting duplicate keys and non-finite scalars."""
        if not isinstance(source, str):
            raise ProjectError("project JSON must be a string")

        def pairs(items: list[tuple[str, Any]]) -> dict:
            result = {}
            for key, value in items:
                if key in result:
                    raise ProjectError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        def constant(value: str) -> None:
            raise ProjectError(f"non-finite JSON scalar: {value}")

        try:
            data = json.loads(source, object_pairs_hook=pairs, parse_constant=constant)
            return cls.from_dict(data)
        except (ValueError, TypeError, RecursionError) as exc:
            if isinstance(exc, ProjectError):
                raise
            raise ProjectError(f"invalid project JSON: {exc}") from exc

    def _check_revision(self, expected_revision: str) -> None:
        if expected_revision != self.revision_id:
            raise RevisionConflict(
                f"expected revision {expected_revision!r}, current {self.revision_id}; "
                "rebase the whole proposed snapshot before retrying")

    def upgrade_schema(self, schema: str, *, expected_revision: str) -> ProjectRevision:
        """Explicit new /2 revision; no rewriting or relabelling of /1 history."""
        self._check_revision(expected_revision)
        if self.schema != PROJECT_SCHEMA or schema != PROJECT_SCHEMA_V2:
            raise ProjectError("only the explicit project /1 -> /2 schema upgrade is supported")
        return ProjectRevision(self.project_id, self.modules, self.instances, self.intent,
                               self.metadata, self.revision_id, self.ir_version, schema)

    def revise(self, *, expected_revision: str,
               modules: Sequence[ModuleDefinition] | None = None,
               instances: Sequence[ModuleInstance] | None = None,
               intent: str | None = None,
               metadata: Mapping[str, Any] | None = None) -> ProjectRevision:
        """Replace supplied complete fields and bind a new immutable parent."""
        self._check_revision(expected_revision)
        return ProjectRevision(
            self.project_id, self.modules if modules is None else modules,
            self.instances if instances is None else instances,
            self.intent if intent is None else intent,
            self.metadata if metadata is None else metadata,
            parent_revision=self.revision_id, ir_version=self.ir_version, schema=self.schema)

    def with_instances(self, instances: Sequence[ModuleInstance], *,
                       expected_revision: str) -> ProjectRevision:
        return self.revise(expected_revision=expected_revision, instances=instances)

    def replace_instance(self, instance: ModuleInstance, *,
                         expected_revision: str) -> ProjectRevision:
        """Replace one whole snapshot, refusing unknown or stale addresses."""
        self._check_revision(expected_revision)
        if not isinstance(instance, ModuleInstance):
            raise ProjectError("replacement must be a ModuleInstance")
        if not any(item.key == instance.key for item in self.instances):
            raise ProjectError(f"unknown instance: {instance.key}")
        return self.with_instances(
            tuple(instance if item.key == instance.key else item
                  for item in self.instances), expected_revision=expected_revision)

    def addressed_outputs(self) -> tuple[tuple[ModuleInstance, NamedOutput, str], ...]:
        """Inert ordered authoring addresses; never materializes geometry.

        Computed once per snapshot: the snapshot is immutable, addresses
        are derived only from its fields, and an address collision is a
        property of those same fields, not of call order. The same tuple
        is returned, and it is immutable: no edit can be made through the
        returned value.
        """
        if self._addressed is not None:
            return self._addressed
        rows, identifiers = [], set()
        for instance in self.instances:
            for output in instance.outputs:
                identifier = output_id(self.project_id, instance.key, output.key)
                if identifier in identifiers:
                    raise ProjectError(f"output identity collision: {identifier}")
                identifiers.add(identifier)
                rows.append((instance, output, identifier))
        addressed = tuple(rows)
        object.__setattr__(self, "_addressed", addressed)
        return addressed

    def geometry_references(self) -> tuple[tuple[ModuleInstance, NamedOutput, str], ...]:
        """Body-owned addresses for inert diff/storage and explicit resolution."""
        return tuple(row for row in self.addressed_outputs() if row[1].geometry is not None)

    def to_program(self) -> dict:
        """Lower in explicit order, without semantic validation or ref rewriting.

        The returned envelope is detached and deliberately has no 'validated'
        flag. ``plan`` is the semantic boundary, including reference ordering,
        result types, supported operations, units and compiler policy.
        """
        ops = []
        for instance, output, identifier in self.addressed_outputs():
            if output.geometry is not None:
                raise GeometryResolutionRequired(
                    f"geometry_resolution_required: {instance.key}/{output.key}; "
                    "explicit materialize_project is required before compilation")
            ops.append({**_thaw(output.operation), "id": identifier})
        # D-1: a project's stable identity rides WITH THE ENVELOPE, rather
        # than being attributed downstream. The same envelope is built
        # independently by
        # geometry_materialization.materialize_project,
        # project_selection.selected_instance_program, and
        # project_submission; without `lineage` here, ordinary
        # materialization DIVERGED from the author's envelope.
        return {"ir_version": self.ir_version, "intent": self.intent,
                "lineage": self.project_id, "ops": ops}

    def plan(self, *, bulk: bool = True) -> PlannedProgram:
        """Validate and type the complete regenerated envelope with KIR."""
        from kir.compiler import plan_program

        if type(bulk) is not bool:
            raise ProjectError("bulk: expected bool, not a truthy coercion")
        return plan_program(self.to_program(), bulk=bulk)
