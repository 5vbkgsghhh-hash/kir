"""Falsifiable XY checks of an explicitly selected authored section change.

Not an engineering/BIM verdict: vertical placement, native room boundaries,
structure and execution are always unevaluated. Policy selects a void chain;
neither output names nor generator parameters infer a shaft or its geometry.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math

from shapely.geometry import Point, Polygon
from shapely.errors import ShapelyError

from kir import contour
from kir.compiler import plan_program
from kir.design_check import spatial_model_from_ops
from kir.diag import KirRefusal
from kir.project import ProjectError, ProjectRevision, _canonical, _hash, _key, _object, _thaw, output_id
from kir.project_refinement import refinement_view
from kir.project_selection import selected_instance_program


class SectionPlanError(ProjectError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class SectionPlanAssessment:
    """In-memory derived report; serializing does not prove its execution."""
    _report: object

    def __post_init__(self):
        object.__setattr__(self, "_report", _object(self._report, "section_plan_assessment"))

    def to_dict(self):
        return _thaw(self._report)

    def dumps(self):
        return _canonical(self._report)


def _policy_keys(values, name, minimum=0):
    if not isinstance(values, (list, tuple)):
        raise SectionPlanError("invalid_section_policy", f"{name}: expected an explicit sequence")
    try:
        for value in values:
            _key(value, name)
    except ProjectError as exc:
        raise SectionPlanError("invalid_section_policy", str(exc)) from exc
    if len(values) < minimum or len(set(values)) != len(values):
        raise SectionPlanError("invalid_section_policy", f"{name}: missing or duplicate subjects")
    return list(values)


def _point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(type(n) in (int, float) and math.isfinite(n) for n in value))


def _geometry(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ShapelyError as exc:
        raise SectionPlanError("plan_geometry_failed", f"{type(exc).__name__}: {exc}") from exc


def _read(project, instance_key):
    instance = next(item for item in project.instances if item.key == instance_key)
    ops = {out.key: {**_thaw(out.operation), "id": output_id(project.project_id, instance.key, out.key)}
           for out in instance.outputs}
    program = {"ir_version": project.ir_version, "intent": project.intent,
               "lineage": project.project_id, "ops": list(ops.values())}
    # spatial_model_from_ops only guards solo-operation mixing, not all compiler
    # semantics. Invoke the actual planner before relying on its geometric reader.
    try:
        planning_program = selected_instance_program(project, instance_key)
        planned = plan_program(planning_program)
    except (KirRefusal, ValueError, TypeError) as exc:
        raise SectionPlanError("invalid_section_program", str(exc)) from exc
    levels = {op["id"]: op["elev_mm"] for op in ops.values() if op["op"] == "create_level"}
    level_for = {}
    for key, op in ops.items():
        selector = op.get("level")
        if (isinstance(selector, dict) and set(selector) == {"by", "value"}
                and selector["by"] == "ref" and isinstance(selector["value"], str)
                and selector["value"] in levels):
            level_for[key] = selector["value"]
    floors, floor_issues = {}, {}
    for key, op in ops.items():
        if op["op"] != "create_floor_by_contour":
            continue
        diagnostics = []
        region = contour.validate_region(op["contour"], [], op["id"], "contour", diagnostics)
        if region is None or not all(contour.edges_are_straight(loop) for loop in [region["outer"], *region["holes"]]):
            floor_issues[key] = "contour_not_literal_straight_region"
            continue
        polygon = _geometry(Polygon, contour.edges_vertices(region["outer"]),
                          [contour.edges_vertices(loop) for loop in region["holes"]])
        if not polygon.is_valid or polygon.is_empty:
            floor_issues[key] = "invalid_plan_polygon"
            continue
        floors[key] = (polygon, [_geometry(Polygon, contour.edges_vertices(loop)) for loop in region["holes"]])
    rooms = [key for key, op in ops.items() if op["op"] == "create_room"]
    walls = [key for key, op in ops.items() if op["op"] == "create_wall"]
    # A wall requiring grounding/curve interpretation can change the partition.
    # Conservatively leave all room-enclosure subjects unevaluated, never omit
    # that wall and certify the smaller set. Slab/seed XY checks remain separate.
    unknown_partition = any(key not in level_for or ops[key].get("arc")
        or not _point(ops[key].get("p0_mm")) or not _point(ops[key].get("p1_mm")) for key in walls)
    unknown_partition |= any(key not in level_for or not _point(ops[key].get("xy")) for key in rooms)
    measured, reasons = set(), {}
    if not unknown_partition:
        model, witness = _geometry(spatial_model_from_ops, program, building_id=project.project_id, close_tol_mm=0.)
        measured = {room.id for room in model.rooms if room.boundary}
        reasons = {key: "shared_partition_face" if ops[key]["id"] in witness.shared_face_room_ids
                   else "room_not_enclosed_by_authored_axes" for key in rooms if ops[key]["id"] not in measured}
    return {"ops": ops, "levels": levels, "level_for": level_for, "floors": floors,
            "floor_issues": floor_issues, "rooms": rooms, "walls": walls,
            "partition_unqualified": bool(unknown_partition), "measured_rooms": measured,
            "room_reasons": reasons, "plan_digest": planned.plan_digest, "program_digest": _hash(planning_program)}


def assess_section_plan_change(before: ProjectRevision, proposed: ProjectRevision, *, source: ProjectRevision,
        instance_key: str, required_void_chain: Sequence[str], protected_instances: Sequence[str]) -> SectionPlanAssessment:
    """Caller-owned policy + exact snapshots -> per-predicate results, no global pass.

    The chain is one explicit continuity group. Its keys must designate floors
    in the baseline and ascend by actual referenced level elevation. Exactly
    one straight hole per member is qualified. A missing proposed subject is
    a violation, not a reduced denominator. Unknown selectors stay unevaluated.
    """
    if any(type(value) is not ProjectRevision for value in (before, proposed, source)):
        raise SectionPlanError("invalid_section_input", "expected exact ProjectRevision snapshots")
    chain = _policy_keys(required_void_chain, "required_void_chain", 2)
    protected = _policy_keys(protected_instances, "protected_instances")
    if instance_key in protected:
        raise SectionPlanError("invalid_section_policy", "the edited section cannot also be protected")
    # Typed lineage validation is a distinct prerequisite, not a geometric test.
    old_lineage = refinement_view(before, instance_key, source=source)
    new_lineage = refinement_view(proposed, instance_key, source=source)
    old_instances = {item.key: item for item in before.instances}
    new_instances = {item.key: item for item in proposed.instances}
    if any(key not in old_instances for key in protected):
        raise SectionPlanError("invalid_section_policy", "protected subject is absent from the baseline")
    old, new = _read(before, instance_key), _read(proposed, instance_key)
    if any(key not in old["ops"] or old["ops"][key]["op"] != "create_floor_by_contour" for key in chain):
        raise SectionPlanError("invalid_section_policy", "void chain must name actual baseline floor outputs")
    ordering = {}
    for label, value in (("before", old), ("proposed", new)):
        elevations = [value["levels"][value["level_for"][key]] for key in chain if key in value["level_for"]]
        ordering[label] = elevations if len(elevations) == len(chain) else None
        if len(elevations) == len(chain) and any(a >= b for a, b in zip(elevations, elevations[1:])):
            raise SectionPlanError("invalid_section_policy", f"{label}: chain must strictly ascend by actual level elevations")
    rows = []
    def row(predicate, subject, status, reason=None, **evidence):
        rows.append({"predicate": predicate, "subject": subject, "status": status,
                     "reason": reason, "evidence": evidence})
    expected = list(dict.fromkeys([*old["ops"], *new["ops"]]))
    for key in expected:
        exists = key in old["ops"] and key in new["ops"]
        same_kind = exists and old["ops"][key]["op"] == new["ops"][key]["op"]
        row("named_subject_retained", key, "evaluated" if same_kind else "violated",
            None if same_kind else "subject_kind_changed" if exists else "subject_added_or_removed",
            before_op_id=old["ops"].get(key, {}).get("id"), proposed_op_id=new["ops"].get(key, {}).get("id"))
    room_keys = list(dict.fromkeys([*old["rooms"], *new["rooms"]]))
    if not room_keys:
        for predicate in ("room_axis_enclosure", "room_seed_in_slab_xy_region"):
            row(predicate, instance_key, "not_evaluated", "no_expected_room_subjects")
    for key in room_keys:
        op = new["ops"].get(key)
        if op is None or op["op"] != "create_room":
            for predicate in ("room_axis_enclosure", "room_seed_in_slab_xy_region"):
                row(predicate, key, "violated", "expected_room_missing")
            continue
        if new["partition_unqualified"]:
            row("room_axis_enclosure", key, "not_evaluated", "partition_contains_unresolved_or_curved_subject")
        else:
            enclosed = op["id"] in new["measured_rooms"]
            row("room_axis_enclosure", key, "evaluated" if enclosed else "violated", new["room_reasons"].get(key),
                op_id=op["id"], endpoint_extension_mm=0.)
        level = new["level_for"].get(key)
        if level is None or not _point(op.get("xy")):
            row("room_seed_in_slab_xy_region", key, "not_evaluated", "room_level_or_point_requires_grounding")
            continue
        # Never match by floor names or ordinal output positions. An unresolved
        # floor selector could designate this same level, so cannot be ignored.
        floor_keys = [k for k, v in new["ops"].items() if v["op"] == "create_floor_by_contour"]
        matching = [k for k in floor_keys if new["level_for"].get(k) == level]
        if any(k not in new["level_for"] for k in floor_keys) or len(matching) != 1:
            row("room_seed_in_slab_xy_region", key, "not_evaluated", "slab_association_not_unique",
                candidate_floor_keys=matching, level_op_id=level)
            continue
        floor_key = matching[0]
        if floor_key not in new["floors"]:
            row("room_seed_in_slab_xy_region", key, "not_evaluated", new["floor_issues"][floor_key], floor_key=floor_key)
            continue
        polygon, _ = new["floors"][floor_key]
        inside = _geometry(polygon.contains, _geometry(Point, op["xy"]))
        row("room_seed_in_slab_xy_region", key, "evaluated" if inside else "violated",
            None if inside else "seed_outside_slab_material_xy", floor_key=floor_key,
            level_op_id=level, point_mm=op["xy"], boundary_included=False)
    def hole(value, key):
        if key not in value["ops"]:
            return None, "expected_floor_missing"
        if key not in value["floors"]:
            return None, value["floor_issues"].get(key, "output_is_not_a_floor")
        holes = value["floors"][key][1]
        if not holes:
            return None, "no_void_in_floor"
        return (holes[0], None) if len(holes) == 1 else (None, "exactly_one_explicit_void_required")
    known_required = {key for key in chain if hole(old, key)[1] is None}
    missing_required = {key for key in known_required if hole(new, key)[1] == "no_void_in_floor"}
    for key in chain:
        a, why_a = hole(old, key)
        b, why_b = hole(new, key)
        why = why_a or why_b
        if why_b == "expected_floor_missing" or key in missing_required:
            row("selected_void_footprint_retained", key, "violated",
                "expected_floor_missing" if why_b == "expected_floor_missing" else "selected_void_missing")
        elif why:
            row("selected_void_footprint_retained", key, "not_evaluated", why)
        else:
            same = _geometry(a.equals, b)
            row("selected_void_footprint_retained", key, "evaluated" if same else "violated",
                None if same else "selected_void_moved_or_reshaped", symmetric_difference_mm2=_geometry(a.symmetric_difference, b).area)
    for left, right in zip(chain, chain[1:]):
        subject = [left, right]
        a, why_a = hole(new, left)
        b, why_b = hole(new, right)
        why = why_a or why_b
        if "expected_floor_missing" in (why_a, why_b):
            row("selected_void_chain_xy_continuity", subject, "violated", "expected_floor_missing")
        elif left in missing_required or right in missing_required:
            row("selected_void_chain_xy_continuity", subject, "violated", "selected_void_missing")
        elif why or ordering["proposed"] is None:
            row("selected_void_chain_xy_continuity", subject, "not_evaluated", why or "chain_level_requires_grounding")
        else:
            same = _geometry(a.equals, b)
            row("selected_void_chain_xy_continuity", subject, "evaluated" if same else "violated",
                None if same else "selected_voids_not_aligned", symmetric_difference_mm2=_geometry(a.symmetric_difference, b).area)
    for key in protected:
        target = new_instances.get(key)
        unchanged = target is not None and _canonical(old_instances[key].to_dict()) == _canonical(target.to_dict())
        row("protected_instance_snapshot", key, "evaluated" if unchanged else "violated",
            None if unchanged else "protected_instance_changed_or_missing",
            before_digest=_hash(old_instances[key].to_dict()), proposed_digest=_hash(target.to_dict()) if target else None)
    for axis in ("vertical_placement", "room_boundary_excludes_slab_holes", "native_realization",
                 "structural_safety", "runtime_liveness", "engineering_adequacy"):
        evidence = {}
        if axis == "vertical_placement":
            evidence["declared_offsets_not_evaluated"] = [{"output_key": key, "field": field, "value_mm": op[field]}
                for key, op in new["ops"].items() for field in ("base_offset_mm", "top_offset_mm", "height_offset_mm") if field in op]
        row(axis, instance_key, "not_evaluated", "outside_authored_xy_predicates", **evidence)
    return SectionPlanAssessment({"schema": "kir-section-plan-assessment/1", "scope": "authored_xy_predicates_only",
        "project_id": proposed.project_id, "instance_key": instance_key,
        "before_revision_id": before.revision_id, "proposed_revision_id": proposed.revision_id,
        "source": new_lineage["source"], "source_binding": "exact_supplied_snapshot_not_ancestry_proof",
        "policy": {"required_void_chain": chain, "protected_instances": protected,
                   "ownership": "caller_selected_not_inferred_from_metadata"},
        "expected_subjects": {"outputs": expected, "rooms": room_keys, "void_chain": chain, "protected_instances": protected},
        "section_plans": {"before": old["plan_digest"], "proposed": new["plan_digest"]},
        "section_program_digests": {"before": old["program_digest"], "proposed": new["program_digest"]},
        "chain_elevations_mm": ordering, "units": {"length": "mm", "area": "mm2"},
        "coordinates": "authored_project_xy_no_metadata_transform", "rows": rows,
        "native_execution": "not_run", "recipe_execution": "not_run", "ancestry": "not_checked",
        "limitations": ["Evaluated rows establish only the named predicate, never an overall pass.",
            "A room seed inside a slab XY region does not prove physical support or native room boundaries.",
            "Exact planar set equality has no construction tolerance, offsets or clearance allowance.",
            "The full enclosing project is not compiled or materialized by this selected-section consumer."]})
