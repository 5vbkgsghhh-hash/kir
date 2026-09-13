"""Explicit body-owned output resolution; inert storage validation is separate.

The selected BRep is the geometry owner. Saved preview triangles/measurements
are never publication inputs: the factory rederives them with the optional
native backend. It does not execute recipes, prove their provenance, measure a
Hausdorff bound, confer BIM meaning, or observe a Revit model.

Loading descriptors/bundles and validate_geometry_bindings do not import OCP.
Native parsing/meshing occurs only in materialize_project, with the same trusted
input/process-isolation boundary as GeometryBundle.read_body. Result budgets do
not limit native CPU/RSS. A serialized sidecar is a claim, not replay evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from kir.midend import PlannedProgram
from kir.occt_geometry import GeometryBundle, GeometryRefusal
from kir.project import ProjectRevision, _canonical, _hash, _object, _thaw
from kir.project_selection import ProjectSelection, validate_project_selection


MATERIALIZATION_SCHEMA = "kir-geometry-materialization/1"
SELECTED_MATERIALIZATION_SCHEMA = "kir-geometry-materialization/2"

#: 🔴 MEMOIZATION BY ADDRESS, NOT BY PROJECT (2026-09-07, measured on 2000
#: bodies). An edit shifts ONE body, but `revision_id` changes because of it,
#: and anything memoized "per revision" misses entirely. Ownership
#: verification and building the materialization row are functions of ONE
#: address: its name, its body (by bytes, via sha), its operation and its
#: instance's parameters. The key carries ALL FIVE, so changing any one of
#: them is a miss and the full work.
#: The cost this removes: `validate_geometry_bindings` at 1.95 s and the
#: `_materialize` loop at 1.11 s on EVERY analysis of 2000 bodies, even
#: though only one had changed.
_ADDRESS_MEMO: dict = {}
#: The limit is named as a number: "a cache with no limit" is a leak under
#: another name. Above it, memory simply stops remembering new entries:
#: slower, but NEVER weaker.
_ADDRESS_MEMO_LIMIT = 40000


def _remember_address(key, value) -> None:
    if len(_ADDRESS_MEMO) >= _ADDRESS_MEMO_LIMIT:
        return
    _ADDRESS_MEMO[key] = value


def _address_key(project, instance, output, identifier, bundle, definitions):
    """Everything the answer for ONE address depends on — and nothing more.

    The body is named by its OWN digests (which are the name of its bytes),
    the operation and parameters by their own canonicalization, the declared
    module recipe by its own. If even one of them diverges, the key differs,
    and the work is redone.
    """
    reference = output.geometry
    recipe = definitions[instance.module_key].recipe
    return (project.project_id, instance.key, output.key, identifier,
            reference.bundle_sha256, reference.body_sha256,
            bundle.digest, bundle.body_digest,
            _canonical(output.operation), _canonical(instance.parameters),
            None if recipe is None else _canonical(recipe.to_dict()))


def validate_geometry_bindings(project: ProjectRevision,
                               bundles: Mapping[str, GeometryBundle]) -> None:
    """Validate references and declared source context WITHOUT native execution.

    Parameters are the complete owning-instance inputs, compared without scalar
    coercion. A declared module recipe must match the source bundle's complete
    RecipePin. A module with no recipe makes no recipe-equivalence claim; the
    bundle's own provenance remains untouched. Equal pins do not prove execution.
    Unreferenced entries may be present in a caller's asset lookup; storage owns
    its separate rule about which new assets a transaction may insert.
    """
    if not isinstance(project, ProjectRevision) or not isinstance(bundles, Mapping):
        raise GeometryRefusal("invalid_input", "expected typed project and bundle mapping")
    _validate_geometry_addresses(project, bundles, project.addressed_outputs())


def _validate_geometry_addresses(project, bundles, addresses):
    definitions = {module.key: module for module in project.modules}
    for instance, output, identifier in addresses:
        reference = output.geometry
        if reference is None:
            continue
        bundle = bundles.get(reference.bundle_sha256)
        if bundle is None:
            raise GeometryRefusal("missing_asset", f"{identifier}: {reference.bundle_sha256}")
        if not isinstance(bundle, GeometryBundle):
            raise GeometryRefusal("invalid_asset", f"{identifier}: expected an inert GeometryBundle")
        # Ownership verification is a pure function of the address key. The
        # bundle's bytes are named by its digest, and the bundle itself only
        # ever arrives here from a verified read: bytes swapped on disk yield
        # a different digest (or a `StoreCorrupt` refusal earlier), i.e. a
        # DIFFERENT key and the full check.
        key = ("bound", _address_key(project, instance, output, identifier, bundle, definitions))
        if key in _ADDRESS_MEMO:
            continue
        if bundle.digest != reference.bundle_sha256 or bundle.body_digest != reference.body_sha256:
            raise GeometryRefusal("binding_mismatch", f"{identifier}: asset/body digest differs from reference")
        manifest = bundle.to_dict()["manifest"]
        expected_binding = {"project_id": project.project_id, "instance_key": instance.key,
                            "output_key": output.key, "op_id": identifier}
        if manifest["binding"] != expected_binding:
            raise GeometryRefusal("binding_mismatch", f"{identifier}: body belongs to another output address")
        if _canonical(manifest["parameters"]) != _canonical(instance.parameters):
            raise GeometryRefusal("parameters_mismatch", f"{identifier}: captured and owning-instance inputs differ")
        recipe = definitions[instance.module_key].recipe
        if recipe is not None and _canonical(manifest["recipe"]) != _canonical(recipe.to_dict()):
            raise GeometryRefusal("recipe_mismatch", f"{identifier}: declared module recipe differs from captured source")
        _remember_address(key, True)


def _materialization_addresses(project, selection):
    addresses = project.addressed_outputs()
    if selection is None:
        return addresses
    validate_project_selection(project, selection)
    return tuple(addresses[index] for index in selection.project_source_indices)


@dataclass(frozen=True, slots=True)
class GeometryMaterialization:
    """One immutable program shared by the scene and backend compiler.

    The factory owns native derivation. Construction checks authoring addresses,
    exact payload/mesh/plan bindings, not BRep equivalence; serialization cannot
    be loaded back as proof that this process ran the kernel. No public loader
    upgrades a stored sidecar into a fresh native derivation.
    """

    project: ProjectRevision
    program: Mapping
    planned: PlannedProgram
    sources: tuple[Mapping, ...]
    selection: ProjectSelection | None = None
    #: 🔴 A DECISION ABOUT THE CONTRACT, NOT ABOUT SPEED (2026-09-07, the
    #: lead's decision). The self-check below answers the question "does this
    #: plan describe THIS program, and have the authored fields not been
    #: rewritten". The question is meaningful for a materialization that
    #: ARRIVED FROM SOME OTHER CARRIER: assembled from saved parts, from
    #: another process, from other hands. For one that WAS BORN HERE — in
    #: `_materialize`, from these same addresses, with this same
    #: `plan_program` — the answer is known by construction: there would be
    #: nothing to compare except itself against itself. The cost of the
    #: question, measured on 2000 bodies: canonicalizing the whole program at
    #: 2.4 s and a SECOND `plan_program` at 1.6 s on EVERY analysis.
    #:
    #: The flag is NOT SERIALIZED (`to_dict` does not carry it) and is set
    #: ONLY by the producer. So anyone who assembles a materialization from
    #: data — including someone who swaps a single row — gets `False` and the
    #: full check. The default favors checking: skipping it must be ASKED FOR.
    _born_here: bool = field(default=False, compare=False, repr=False)

    def __post_init__(self):
        from kir.compiler import plan_program

        if not isinstance(self.project, ProjectRevision) or not isinstance(self.planned, PlannedProgram):
            raise GeometryRefusal("invalid_materialization", "expected typed project and plan")
        addresses = _materialization_addresses(self.project, self.selection)
        program = _object(self.program, "materialized_program")
        if not isinstance(self.sources, tuple):
            raise GeometryRefusal("invalid_materialization", "sources must be an immutable tuple")
        sources = tuple(_object(row, "geometry_source") for row in self.sources)
        if any(not isinstance(row.get("op_id"), str) for row in sources):
            raise GeometryRefusal("invalid_materialization", "source rows require output IDs")
        by_id = {row.get("op_id"): row for row in sources}
        references = {oid: output.geometry for _, output, oid in addresses if output.geometry is not None}
        if len(by_id) != len(sources) or set(by_id) != set(references):
            raise GeometryRefusal("invalid_materialization", "source rows do not match body-owned outputs")
        expected = []
        operations = program.get("ops", ())
        if not isinstance(operations, tuple) or len(operations) != len(addresses):
            raise GeometryRefusal("invalid_materialization", "materialized output count differs from project")
        for (_, output, identifier), operation in zip(addresses, operations, strict=True):
            row = {**_thaw(output.operation), "id": identifier}
            if output.geometry is not None:
                if not isinstance(operation, Mapping) or "mesh" not in operation:
                    raise GeometryRefusal("invalid_materialization", f"{identifier}: missing derived mesh")
                source = by_id[identifier]
                if (source.get("source_bundle_sha256") != output.geometry.bundle_sha256
                        or source.get("source_body_sha256") != output.geometry.body_sha256
                        or source.get("mesh_sha256") != _hash(operation["mesh"])):
                    raise GeometryRefusal("invalid_materialization", f"{identifier}: derived source/mesh mismatch")
                row["mesh"] = _thaw(operation["mesh"])
            expected.append(row)
        envelope = {"ir_version": self.project.ir_version, "intent": self.project.intent,
                    "lineage": self.project.project_id, "ops": expected}
        # 🔴 THE SECOND `plan_program` STAYS FOR A MATERIALIZATION FROM SOME
        # OTHER CARRIER, AND HERE IS WHY IT CANNOT BE REPLACED BY A ROW
        # COMPARISON. `plan_digest` is the sha256 over the plan's
        # `_unsigned_evidence()`, and a plan is a TRANSFORMATION of the
        # program; the only link between them is to repeat the
        # transformation. Replacing it with a comparison of
        # `PlannedOp.to_dict()` against the original operation would only be
        # valid under identity across the WHOLE registry, and there is none: a
        # probe on 2026-09-07 across 83 ops gave 49 identical, 7 THAT
        # DIVERGED, and 27 unbuilt. The ones that diverge are `author_family`
        # (+template), `create_column` (+category), `create_type`
        # (+category), `create_wall` (+height_mm), `create_window`
        # (+sill_mm), `query_count` (+where) and `query_list`
        # (+fields/limit/where) — the plan fills in silent defaults, i.e.
        # `to_dict()` is a NORMALIZED payload, not the original operation.
        if not self._born_here:
            if _canonical(program) != _canonical(envelope):
                raise GeometryRefusal("invalid_materialization", "materialization changed authored fields or output order")
            if plan_program(_thaw(program), bulk=self.planned.bulk).plan_digest != self.planned.plan_digest:
                raise GeometryRefusal("invalid_materialization", "plan does not describe this materialized program")
        object.__setattr__(self, "program", program)
        object.__setattr__(self, "sources", sources)

    def to_program(self) -> dict:
        return _thaw(self.program)

    def to_dict(self) -> dict:
        payload = {"schema": MATERIALIZATION_SCHEMA if self.selection is None else SELECTED_MATERIALIZATION_SCHEMA,
                   "project_id": self.project.project_id,
                   "project_revision_id": self.project.revision_id,
                   "plan_digest": self.planned.plan_digest, "program": self.to_program(),
                   "sources": [_thaw(row) for row in self.sources],
                   "scope": "body_to_triangle_representation", "native_bim": "not_claimed",
                   "revit_execution": "not_run", "geometric_error_bound": "not_measured",
                   "recipe_execution": "not_run"}
        if self.selection is not None:
            payload["selection"] = self.selection.to_dict()
            payload["scope"] = "selected_body_to_triangle_representation"
        return {**payload, "materialization_digest": _hash(payload)}


def materialize_project(project: ProjectRevision, bundles: Mapping[str, GeometryBundle],
                        *, bulk: bool = False) -> GeometryMaterialization:
    """Resolve all body outputs explicitly, or return no partial program.

    Ordinary authored operations are copied without modification. Original
    project/assets are immutable and never updated, even if a later body,
    tessellation budget, or compiler check refuses. No automatic coarsening.
    """
    if type(bulk) is not bool:
        raise GeometryRefusal("invalid_input", "bulk must be bool")
    validate_geometry_bindings(project, bundles)
    return _materialize(project, bundles, project.addressed_outputs(), bulk, None)


def materialize_selection(project: ProjectRevision, selection: ProjectSelection,
                          bundles: Mapping[str, GeometryBundle], *, bulk: bool = False) -> GeometryMaterialization:
    """Derive only selected closure bodies while retaining the FULL project.

    Unselected assets need not be supplied and are never parsed or planned.
    Selected assets retain the same BRep owner and validation as whole-project
    materialization. This is not whole-project geometry/compilation coverage.
    """
    if type(project) is not ProjectRevision or not isinstance(bundles, Mapping) or type(bulk) is not bool:
        raise GeometryRefusal("invalid_input", "expected exact project, bundle lookup and boolean bulk policy")
    addresses = _materialization_addresses(project, selection)
    if selection is None:
        raise GeometryRefusal("invalid_input", "explicit ProjectSelection required")
    _validate_geometry_addresses(project, bundles, addresses)
    return _materialize(project, bundles, addresses, bulk, selection)


def _materialize(project, bundles, addresses, bulk, selection):
    from kir.compiler import plan_program

    operations, sources = [], []
    definitions = {module.key: module for module in project.modules}
    for instance, output, identifier in addresses:
        operation = {**_thaw(output.operation), "id": identifier}
        if output.geometry is not None:
            original = bundles[output.geometry.bundle_sha256]
            # 🔴 MEMOIZATION FOR THE MATERIALIZATION ROW USED TO BE SET UP HERE
            # AND WAS REMOVED BASED ON A MEASUREMENT (2026-09-07). The
            # address-based key worked, but the payoff turned out to be −0.6 s
            # (a deep copy of the mesh costs more than building it, once the
            # derivation is already memoized on the bundle), while peak RSS
            # grew 945 -> 1422 MB on 2000 bodies. Memory that costs 477 MB and
            # does NOT speed anything up is a leak with a good name. What
            # remains here is only the OWNERSHIP-VERIFICATION memoization
            # (`_validate_geometry_addresses`), which gives −1.0 s and stores flags.
            derived = original.rederive_preview()
            # Only the schema-declared mesh slot is filled. Name/category and
            # all ordinary operation payloads retain their authored ownership.
            operation["mesh"] = derived.fallback_op(name="Derived body preview")["mesh"]
            manifest = derived.manifest
            sources.append({
                "op_id": identifier, "source_bundle_sha256": original.digest,
                "source_body_sha256": original.body_digest,
                "units": manifest["units"], "frame": manifest["frame"],
                # 🔴 THE TOLERANCE TRAVELS WITH THE BODY. Measured
                # 2026-09-07: not one of the three readers (the standalone
                # scene, analysis, DirectShape emission) could name the
                # selected body's `modeling_tolerance_mm` — the field lived
                # only inside the bundle. A reader that knows the revision
                # and the frame but not the tolerance is not verifying the
                # WHOLE selected geometry.
                "modeling_tolerance_mm": manifest["modeling_tolerance_mm"],
                "backend": manifest["backend"], "tessellation": manifest["preview"],
                "mesh_sha256": _hash(operation["mesh"]),
                "measurements": manifest["measurements"],
                "measurements_space": "body_local", "mesh_space": "project",
                "mesh_origin": "rederived_from_brep",
                "stored_preview_bytes_equal": (
                    original.manifest["preview"]["sha256"] == manifest["preview"]["sha256"]),
                "module_recipe_match": ("matched_declared_pin" if definitions[instance.module_key].recipe
                                        is not None else "not_claimed"),
            })
        operations.append(operation)
    # D-1: the project's stable identity travels with the envelope (see emit_core._program_stamp).
    program = {"ir_version": project.ir_version, "intent": project.intent,
               "lineage": project.project_id, "ops": operations}
    planned = plan_program(program, bulk=bulk)
    # The flag is set ONLY by the producer, and only here: the program, the
    # plan and the rows were assembled in this very call from these same addresses.
    return GeometryMaterialization(project, program, planned, tuple(sources), selection,
                                   _born_here=True)


# ─────────────────────────────────────────────────────────────────────────────
# THE MEP FIELD PRODUCER: AUTHORED OPERATION -> THE LANGUAGE'S WORDS ABOUT A ROUTE
# ─────────────────────────────────────────────────────────────────────────────
# 🔴 WHY THIS IS HERE, MEASURED 2026-09-08. `kir/clash/repair_profile.py` can
# refuse a pipe by name — but it read ONLY `instance.parameters`, while the
# authored program puts its fields into the output's OPERATION
# (`author_project` copies the op's payload into `NamedOutput.operation`).
# Measured with a probe: a revision with an authored `create_duct` (system
# declared, axis with a 4.9937617% slope) gave
# `repair_profile.classify(...) is None` — the profile treated the duct as a
# BLOCK, and `propose_fix` refused with WORDS ABOUT THE WRONG THING: "raise_clear
# needs a box parameter named 'run'… this output's shape is parameterised
# otherwise" — that is, about PARAMETERIZATION where the question was about TYPE.
#
# 🔴 WHAT THIS PRODUCER DOES NOT DO. It sets up not a single NEW field name
# and no second carrier of the rule: it TRANSLATES the registry operation into
# the very same words the KIR language itself uses to declare a route —
#   `p0_mm`/`p1_mm`              a single element's axis (`ops_mep`);
#   `nodes`/`segments[from,to]`  the connector graph (`ops_connect`);
#   `segments[].slope_min_pct`   the slope floor (`route_mep`, KIR-X004);
#   `system_type`                system membership;
#   `category`                   a `BuiltInCategory` member FROM THE REGISTRY
#                                (`kir.spec.op_result_categories`), not from a
#                                local table: a local table has already once
#                                diverged from the registry (`clash_bundle`,
#                                `REGISTRY_GAPS`).
# Nothing is STORED: fields are derived from the operation on every read, so
# the revision does not get a second copy of the same numbers that could
# diverge from the first. Production here is a READ, called by its own name.
#
# 🔴 BOUNDARY. Capturing an existing building (`decompile/*`) does NOT
# produce MEP fields: a decompiled duct arrives as a mass with a box, and the
# profile judges it by `metadata.source_category`, as it always did. There is
# no live Revit here, and none is asked.

#: A single element: axis `p0_mm`/`p1_mm` in absolute mm.
MEP_AXIS_OPS: tuple[str, ...] = (
    "create_pipe", "create_duct", "create_cable_tray", "create_conduit",
    "create_pipe_placeholder", "create_duct_placeholder",
)
#: A route graph: one op — many edges; `segments[]` CARRIES `slope_min_pct`.
MEP_GRAPH_OPS: tuple[str, ...] = (
    "create_pipe_system", "route_pipe_system", "route_duct_system",
)
#: A flexible route: a `path` polyline. It has NO `p0_mm`/`p1_mm` axis — the
#: chord between the polyline's ends is not its axis, and declaring it one
#: would misstate the slope. The ends are still CONNECTORS, and they are named.
MEP_PATH_OPS: tuple[str, ...] = ("create_flex_duct", "create_flex_pipe")

#: A closed list: ALL registry operations whose category lies on the `mep`
#: side of the `kir.clash.hulls.KIND_TABLE` table. Today there are 11 of them,
#: and the same number here — the equality is guarded by a test, not a promise.
MEP_FIELD_OPS: tuple[str, ...] = MEP_AXIS_OPS + MEP_GRAPH_OPS + MEP_PATH_OPS


def _mep_point(value):
    """A point `[x, y, z]` in mm — or None. No rounding, no completion."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        return None
    return [float(v) for v in value]


def _mep_number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _selector_name(word):
    """A name from KIR's FROZEN reference dialect, or None.

    `sel` is `{"by": "name"|"element_id"|"ref"|"default", "value": …}`. A
    plain string is accepted too: that is how the field arrives from capture
    parameters. For `default` the word `default` is returned: a system WAS
    CHOSEN ("the only one in the snapshot"), and a silent None would read as
    "there is no system".
    """
    if isinstance(word, str):
        return word or None
    if isinstance(word, Mapping):
        by, value = word.get("by"), word.get("value")
        if by == "name" and isinstance(value, str) and value:
            return value
        if by in ("element_id", "ref") and value is not None:
            return f"{by}:{value}"
        if by == "default":
            return "default"
    return None


def _mep_category(name: str):
    """The operation's category — FROM THE REGISTRY. More than one -> None, not a guess.

    The registry's silence does NOT grant permission: all eleven ops still
    have their produced connectors, and the profile will refuse via
    `connectors_declared` — a different name, but the same truth. So `None`
    is acceptable here, not an exception: a named degradation, not a silent one.
    """
    try:
        from kir.spec import op_result_categories

        categories = tuple(op_result_categories({"op": name}) or ())
    except Exception:  # noqa: BLE001 — no registry: no category, and this is stated
        return None
    return categories[0] if len(categories) == 1 else None


def _mep_axis_fields(operation) -> dict:
    p0 = _mep_point(operation.get("p0_mm"))
    p1 = _mep_point(operation.get("p1_mm"))
    if p0 is None or p1 is None:
        return {}
    # ENDS ARE CONNECTORS. A single element has exactly two of them, and
    # `nodes`/`segments` are the same words the graph uses to declare `ops_connect`.
    segment = {"from": "p0", "to": "p1"}
    diameter = _mep_number(operation.get("diameter_mm"))
    if diameter is not None:
        segment["diameter_mm"] = diameter
    return {"p0_mm": p0, "p1_mm": p1,
            "nodes": {"p0": p0, "p1": p1}, "segments": [segment]}


def _mep_graph_fields(operation) -> dict:
    """The route graph — as declared. THAWED, and this is not cosmetic.

    🔴 MEASURED 2026-09-08. In a real revision the operation is frozen
    (`kir.project._freeze`): a nested object becomes a `MappingProxyType`, and
    a list becomes a `tuple`. Yet the profile asks `isinstance(segs, list)`
    and `isinstance(seg, dict)` (`repair_profile._segments`/`_declared_slope`),
    and against a frozen graph both would return "no" — the KIR-X004 slope
    floor would disappear SILENTLY, exactly the kind of bug this producer
    exists to catch. Hence `_thaw(tuple(...))`: `_thaw` unpacks a Mapping and
    a tuple recursively, but stops on a bare list, so the list is first
    turned into a tuple.
    """
    fields: dict = {}
    nodes = operation.get("nodes")
    if isinstance(nodes, Mapping) and nodes:
        fields["nodes"] = _thaw(nodes)
    elif isinstance(nodes, (list, tuple)) and nodes:
        fields["nodes"] = _thaw(tuple(nodes))
    segments = operation.get("segments")
    if isinstance(segments, (list, tuple)) and segments:
        # PASSED THROUGH AS IS: `slope_min_pct` lives inside the edge, and
        # rewriting it here would mean setting up a second carrier of KIR-X004.
        fields["segments"] = _thaw(tuple(segments))
    return fields


def _mep_path_fields(operation) -> dict:
    path = operation.get("path")
    if not isinstance(path, (list, tuple)):
        return {}
    points = [_mep_point(item) for item in path]
    if len(points) < 2 or any(point is None for point in points):
        return {}
    return {"nodes": {f"p{i}": point for i, point in enumerate(points)},
            "segments": [{"from": f"p{i}", "to": f"p{i + 1}"}
                         for i in range(len(points) - 1)]}


def mep_fields(operation) -> dict:
    """The MEP fields CARRIED by the authored registry operation itself.

    `{}` — the operation says nothing about a route (and this IS an answer,
    not an omission). Otherwise — a dict in the language's own words:
    `category`, `system_type` and connectors (`nodes`/`segments`), plus the
    `p0_mm`/`p1_mm` axis wherever the op carries one.
    """
    if not isinstance(operation, Mapping):
        return {}
    name = operation.get("op")
    if not isinstance(name, str) or name not in MEP_FIELD_OPS:
        return {}
    if name in MEP_AXIS_OPS:
        fields = _mep_axis_fields(operation)
    elif name in MEP_GRAPH_OPS:
        fields = _mep_graph_fields(operation)
    else:
        fields = _mep_path_fields(operation)
    category = _mep_category(name)
    if category is not None:
        fields["category"] = category
    system = _selector_name(operation.get("system_type"))
    if system is not None:
        fields["system_type"] = system
    return fields


__all__ = ["MATERIALIZATION_SCHEMA", "SELECTED_MATERIALIZATION_SCHEMA", "GeometryMaterialization", "validate_geometry_bindings",
           "materialize_project", "materialize_selection",
           "MEP_AXIS_OPS", "MEP_GRAPH_OPS", "MEP_PATH_OPS", "MEP_FIELD_OPS",
           "mep_fields"]
