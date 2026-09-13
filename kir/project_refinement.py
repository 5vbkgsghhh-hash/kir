"""Explicit authored 1:N schematic lineage in the existing instance metadata.

This annotates evaluated snapshots; it never executes recipes, plans KIR, reads
geometry or proves ancestry. The containing revision binds the target; storing
that revision's own hash inside its metadata would be a circular definition.
Store/Project keep arbitrary drafts inert. Every typed view rechecks this block
and the exact supplied source, rather than trusting an earlier JSON assertion.
"""
from __future__ import annotations

import math

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from kir import spec
from kir.project import (ModuleInstance, ProjectError, ProjectRevision, _canonical,
                         _digest, _fields, _hash, _key, _thaw, output_id)
from kir.registry_base import EffectKind, IdentityCardinality, ReferenceKind


REFINEMENT_SCHEMA = "kir-schematic-refinement/1"
#: 🔴 VERSION `/2` IS NOT A NEW STORAGE SCHEMA, IT IS THE SAME RECORD WITH TWO
#: MORE FIELDS. `/1` is read exactly as it was read before, letter for
#: letter; no old snapshot needs migration on disk. The difference is exactly
#: what `/1` had no way to say:
#:   * A LIVE SOURCE ADDRESS. `/1` knew only the HISTORICAL pin
#:     (`revision_id` + `output_digest`), so the source lived in the PAST:
#:     refinement REPLACED the concept, nothing of its output stayed in mind
#:     (recon measurement: 0 occurrences), and "change the atrium outline
#:     AFTER refinement" had no one to address. `/2` adds `live_instance_key`
#:     — WHERE THAT SAME output lives NOW. The historical pin is NOT removed
#:     or weakened by this: it still says what it was derived from, while the
#:     live address says where to look when editing. Storing the hash of the
#:     current revision inside itself is impossible (a circular definition,
#:     per the module header), so the live address is keys, not a revision
#:     digest.
#:   * THE SOURCE SIDE. `/1` knew ONE source for all descendants, and the
#:     question "which part of the shell produced this wall" was
#:     inexpressible. `/2` carries `parts` — the author's breakdown of
#:     descendants by source part (`atrium`, `north_facade`, `floor_k`), and
#:     this breakdown is STRICT: every member belongs to exactly one part, so
#:     two different parts cannot yield the same set.
REFINEMENT_SCHEMA_V2 = "kir-schematic-refinement/2"
_SCHEMAS = (REFINEMENT_SCHEMA, REFINEMENT_SCHEMA_V2)
_LIVE_ADDRESS = "live_instance_key"

#: Role -> (op name, reference kind, categories). `None` in categories means
#: "the OP ITSELF assigns the categories, not this table."
#:
#: 🔴 WHY AN OPENING'S CATEGORY IS NOT A CONSTANT. `create_opening` declares
#: THREE categories (`OST_FloorOpening`, `OST_RoofOpening`,
#: `OST_CeilingOpening`) — which one comes out is decided by the opening's
#: HOST, not by the role's author. Recording just one here would mean
#: inventing on the registry's behalf; recording all three and requiring the
#: sets to match would also be untrue, because the op returns one. So for
#: such roles the category is taken from the op and only checked for being
#: non-empty.
_ROLES = {
    "level": ("create_level", ReferenceKind.LEVEL, ("OST_Levels",)),
    "slab": ("create_floor_by_contour", ReferenceKind.ELEMENT, ("OST_Floors",)),
    "wall": ("create_wall", ReferenceKind.WALL, ("OST_Walls",)),
    "space": ("create_room", ReferenceKind.ELEMENT, ("OST_Rooms",)),
    # added 07.09.2026 — openings and roofing; the registry contract was checked by measurement
    "opening": ("create_opening", ReferenceKind.ELEMENT, None),
    "window": ("create_window", ReferenceKind.ELEMENT, ("OST_Windows",)),
    "door": ("create_door", ReferenceKind.ELEMENT, ("OST_Doors",)),
    "roof": ("create_roof", ReferenceKind.ELEMENT, ("OST_Roofs",)),
    # author decisions that live in a SEPARATE instance: a type has no
    # category at all (`op_result_categories` -> None), and this is not a
    # gap but a property of the kind: a type is not a model element.
    "wall_type": ("create_wall_type", ReferenceKind.WALL_TYPE, None),
}

#: 🔴 THE CURTAIN GRID REFUSES BY NAME, RATHER THAN STAYING SILENT OR LYING.
#: Measurement on 07.09.2026 against the registry: `create_curtain_grid_line`
#: carries no `reference_kind` at all (`None`), and `set_curtain_panel` is
#: `EffectKind.MUTATE` outright, meaning it creates no addressable
#: descendant. The role contract requires ONE created element with a known
#: reference kind; neither satisfies it. Recording them here as "good enough
#: for now" would mean declaring lineage where there is nothing to address.
#: The refusal is named — and named before the author spends a turn.
_REFUSED_ROLES = {
    "curtain_grid": "create_curtain_grid_line не несёт reference_kind: сетке нечего адресовать как потомку",
    "curtain_panel": "set_curtain_panel — MUTATE над существующей панелью, а не создание потомка",
    "facade_panel": "фасадная панель приходит из сетки; отдельного создающего опа с родом ссылки нет",
}
_LEGACY_FIELDS = {"kind", "geometry_preserved", "losses", "inactive_parameters"}


class RefinementError(ProjectError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _require(condition, code, message):
    if not condition:
        raise RefinementError(code, message)


def _instance(value):
    _require(type(value) is ModuleInstance, "invalid_refinement", "expected exact ModuleInstance")


def _project(value):
    _require(type(value) is ProjectRevision, "invalid_refinement", "expected exact ProjectRevision")


def _names(values, name, *, allow_empty=False):
    _require(isinstance(values, (list, tuple)), "invalid_refinement", f"{name}: expected a sequence")
    try:
        for value in values:
            _key(value, name)
    except ProjectError as exc:
        raise RefinementError("invalid_refinement", str(exc)) from exc
    _require((allow_empty or bool(values)) and len(set(values)) == len(values),
             "invalid_refinement", f"{name}: empty/duplicate names")
    return list(values)


def _qualifies(output, role):
    """One output checked against the REGISTRY contract for the declared role."""
    _require(role not in _REFUSED_ROLES, "unsupported_facade_grid_role",
             _REFUSED_ROLES.get(role, ""))
    _require(isinstance(role, str) and role in _ROLES, "role_contract_mismatch",
             "unsupported authored role")
    name, reference_kind, categories = _ROLES[role]
    contract = spec.OPS.get(name)
    _require(output.operation["op"] == name and output.geometry is None and contract is not None,
             "role_contract_mismatch", f"{output.key}: role does not qualify this output")
    result = contract.result
    _require(contract.effect is EffectKind.CREATE
             and result.identity_cardinality is IdentityCardinality.ONE
             and result.reference_kind is reference_kind and result.identity_field == "id",
             "role_contract_mismatch", f"{output.key}: current registry contract differs")
    actual = spec.op_result_categories(output.operation)
    if categories is None:
        # The op assigns the category. We check exactly what can be checked:
        # the registry either KNOWS something about it (a tuple) or knows it
        # has none (None for types). Inventing an expectation here would mean
        # substituting the registry with a table.
        _require(actual is None or (isinstance(actual, tuple) and len(actual) >= 1),
                 "role_contract_mismatch", f"{output.key}: registry categories are unreadable")
    else:
        _require(actual == categories, "role_contract_mismatch",
                 f"{output.key}: current registry contract differs")


def _roles(instance, members, *, project=None):
    """Member roles. A member WITHOUT `instance_key` lives in this instance.

    🔴 A FOREIGN INSTANCE DID NOT APPEAR OUT OF CONVENIENCE. Two
    `create_wall_type` calls from the example section live in a SEPARATE
    instance (`section-types`), and this is visible by instrument: out of 23
    outputs of the section program, the `/1` record addressed 21, and two
    types were UNADDRESSABLE. The types cannot be forced to move to the
    walls — their separateness is itself the author's decision (one type
    shared by all walls). So a member is entitled to name a foreign instance
    of the SAME project, while "exact and in order" coverage is required of
    ONE'S OWN members: one's own is covered in full, the foreign one is named
    explicitly and checked against the same role contract.
    """
    _require(isinstance(members, list), "invalid_refinement", "members must be an array")
    own, foreign = [], []
    for member in members:
        allowed = {"output_key", "role"} | ({"part_id"} if "part_id" in member else set()) \
            | ({"instance_key"} if "instance_key" in member else set())
        _fields(member, allowed, "refinement.member")
        _key(member["output_key"], "member.output_key")
        if "part_id" in member:
            _key(member["part_id"], "member.part_id")
        if "instance_key" in member:
            _key(member["instance_key"], "member.instance_key")
            foreign.append(member)
        else:
            own.append(member)
    keys = [member["output_key"] for member in own]
    _require(len(keys) >= 2 and keys == [output.key for output in instance.outputs],
             "member_coverage_mismatch", "members must cover every output exactly once in snapshot order")
    by_key = {output.key: output for output in instance.outputs}
    for member in own:
        _qualifies(by_key[member["output_key"]], member["role"])
    if not foreign:
        return
    _require(len({(m["instance_key"], m["output_key"]) for m in foreign}) == len(foreign),
             "member_coverage_mismatch", "foreign members must be distinct addresses")
    if project is None:
        # Structure is checked; membership only where a project snapshot
        # exists. A foreign output cannot be silently declared existing.
        return
    instances = {item.key: item for item in project.instances}
    for member in foreign:
        _require(member["instance_key"] != instance.key, "member_coverage_mismatch",
                 "a foreign member cannot name the annotated instance itself")
        owner = instances.get(member["instance_key"])
        _require(owner is not None, "member_coverage_mismatch",
                 f"{member['instance_key']}: foreign member instance is absent from this project")
        output = next((item for item in owner.outputs if item.key == member["output_key"]), None)
        _require(output is not None, "member_coverage_mismatch",
                 f"{member['output_key']}: foreign member output is absent")
        _qualifies(output, member["role"])


def _parts(record, members):
    """Source parts are a MEMBER FIELD, not a second list. And this is not a style choice.

    🔴 THE FIRST EDITION STORED `parts` AS A SEPARATE LIST, AND IT BROKE
    WITHIN THE HOUR. The strip produced five `part_coverage_mismatch`
    refusals on an honest scenario: a test removes one section output, the
    member disappears — and the parts list keeps naming it. Two carriers of
    one fact are bound to diverge; the only question is when. So a part lives
    in EXACTLY one place: on the member. Coverage is then complete by
    construction (every member has exactly one field), and "two different
    parts yield different sets" is also by construction, not by checking.

    What is checked here is exactly what the field does not guarantee: if a
    part is named on even one member, it must be named on ALL of them. A
    half-done labeling would silently leave descendants without a part
    address — the very hole `/2` was set up to close.
    """
    named = [member for member in members if "part_id" in member]
    if not named:
        return None
    _require(len(named) == len(members), "part_coverage_mismatch",
             "part_id must be declared for every member or for none")
    return {member["output_key"]: member["part_id"] for member in named}


def _record(instance, *, project=None):
    """Check structure/roles only. Actual source payload needs refinement_view."""
    _instance(instance)
    record = _thaw(instance.metadata.get("refinement"))
    _require(isinstance(record, dict) and "schema" in record, "legacy_unbound_refinement",
             "loose/missing metadata does not identify a qualified historical source")
    _require(record["schema"] in _SCHEMAS, "unsupported_refinement_schema", "unknown record schema")
    two = record["schema"] == REFINEMENT_SCHEMA_V2
    try:
        _fields(record, {"schema", "kind", "source", "members", *_LEGACY_FIELDS}, "refinement")
        _require(record["kind"] == "schematic_redesign" and record["geometry_preserved"] is False,
                 "invalid_refinement", "only explicit schematic_redesign with boolean false is qualified")
        source_fields = {"project_id", "revision_id", "instance_key", "output_key", "output_digest"}
        if two and _LIVE_ADDRESS in record["source"]:
            source_fields = source_fields | {_LIVE_ADDRESS}
        source = _fields(record["source"], source_fields, "refinement.source")
        if _LIVE_ADDRESS in source:
            _key(source[_LIVE_ADDRESS], "source." + _LIVE_ADDRESS)
        for name in ("project_id", "instance_key", "output_key"):
            _key(source[name], f"source.{name}")
        for name in ("revision_id", "output_digest"):
            _digest(source[name], f"source.{name}")
        _names(record["losses"], "losses")
        inactive = _names(record["inactive_parameters"], "inactive_parameters", allow_empty=True)
        _require(all(name in instance.parameters for name in inactive), "invalid_refinement",
                 "inactive parameter is not present in the snapshot")
        _roles(instance, record["members"], project=project)
        if two:
            _parts(record, record["members"])
        alias = [output_id(source["project_id"], source["instance_key"], source["output_key"])]
        _require(_canonical(instance.metadata.get("refines")) == _canonical(alias), "source_alias_mismatch",
                 "legacy refines must be the exact derived source-address projection")
        return record
    except RefinementError:
        raise
    except (ProjectError, TypeError, KeyError, ValueError) as exc:
        raise RefinementError("invalid_refinement", str(exc)) from exc


def _source_output(source, instance_key, output_key):
    _project(source)
    _require(source.ir_version == spec.IR_VERSION, "unsupported_refinement_ir", "source IR is not qualified by current contracts")
    try:
        _key(instance_key, "source_instance_key")
        _key(output_key, "source_output_key")
    except ProjectError as exc:
        raise RefinementError("invalid_refinement", str(exc)) from exc
    instance = next((item for item in source.instances if item.key == instance_key), None)
    output = next((item for item in instance.outputs if item.key == output_key), None) if instance else None
    _require(output is not None, "source_binding_mismatch", "source named output does not exist")
    _require(output.operation["op"] == "create_solid_blend", "unsupported_refinement_source",
             "this first contract qualifies a conceptual blend, not arbitrary native/mesh sources")
    return output


def _replacement_record_is_compatible(replacement, record):
    existing = _thaw(replacement.metadata.get("refinement"))
    if existing is None and "refinement" not in replacement.metadata:
        pass
    else:
        _require(isinstance(existing, dict), "conflicting_refinement", "replacement annotation is malformed")
        if "schema" in existing:
            existing = _record(replacement)
            _require(_canonical(existing) == _canonical(record), "conflicting_refinement",
                     "replacement already declares another typed refinement")
        else:
            _require(set(existing) == _LEGACY_FIELDS
                     and _canonical(existing) == _canonical({name: record[name] for name in _LEGACY_FIELDS}),
                     "conflicting_refinement", "replacement's loose declaration contradicts the typed record")
    alias = replacement.metadata.get("refines")
    source = record["source"]
    _require("refines" not in replacement.metadata or _canonical(alias) == _canonical([
        output_id(source["project_id"], source["instance_key"], source["output_key"])]),
        "source_alias_mismatch", "replacement contains another legacy source address")


def _annotated(replacement, record, *, project=None):
    _instance(replacement)
    _replacement_record_is_compatible(replacement, record)
    source = record["source"]
    result = replace(replacement, metadata={**_thaw(replacement.metadata), "refinement": record,
        "refines": [output_id(source["project_id"], source["instance_key"], source["output_key"])]})
    _record(result, project=project)
    return result


def annotate_schematic_refinement(source: ProjectRevision, replacement: ModuleInstance, *,
        source_instance_key: str, source_output_key: str, roles: Mapping[str, str],
        losses: Sequence[str], inactive_parameters: Sequence[str] = (),
        parts: Mapping[str, Sequence[str]] | None = None,
        foreign_members: Sequence[Mapping[str, str]] = (),
        live_instance_key: str | None = None,
        project: ProjectRevision | None = None) -> ModuleInstance:
    """Annotate an existing evaluated target; source binding is not ancestry proof.

    `parts` is the author's breakdown of descendants by SOURCE part
    (`{"atrium": [...], "north_facade": [...]}`); without it the record stays
    at version `/1` and behaves exactly as before, letter for letter.
    `foreign_members` are descendants living in a SEPARATE instance of the
    same project (for the examples these are two `create_wall_type` calls):
    `{"instance_key", "output_key", "role"}`.
    `live_instance_key` is the instance in which THAT SAME source output
    lives NOW (the concept is kept in mind, not only in history). The
    historical pin remains in place: it says "what it was derived from,"
    the live address says "where to look when editing."
    """
    _instance(replacement)
    source_output = _source_output(source, source_instance_key, source_output_key)
    _require(isinstance(roles, Mapping), "member_coverage_mismatch", "roles must be an output-key mapping")
    _require(set(roles) == {output.key for output in replacement.outputs}, "member_coverage_mismatch",
             "roles must name exactly the replacement outputs")
    two = parts is not None or bool(foreign_members) or live_instance_key is not None
    members = [{"output_key": output.key, "role": roles[output.key]} for output in replacement.outputs]
    for foreign in foreign_members:
        _require(isinstance(foreign, Mapping) and set(foreign) >= {"instance_key", "output_key", "role"},
                 "member_coverage_mismatch", "foreign member needs instance_key/output_key/role")
        members.append({"output_key": foreign["output_key"], "role": foreign["role"],
                        "instance_key": foreign["instance_key"]})
    reference = {"project_id": source.project_id, "revision_id": source.revision_id,
                 "instance_key": source_instance_key, "output_key": source_output_key,
                 "output_digest": _hash(source_output.to_dict())}
    if live_instance_key is not None:
        reference[_LIVE_ADDRESS] = live_instance_key
    record = {"schema": REFINEMENT_SCHEMA_V2 if two else REFINEMENT_SCHEMA,
        "kind": "schematic_redesign", "source": reference, "members": members,
        "geometry_preserved": False, "losses": _names(losses, "losses"),
        "inactive_parameters": _names(inactive_parameters, "inactive_parameters", allow_empty=True)}
    if parts is not None:
        _require(isinstance(parts, Mapping) and parts, "part_coverage_mismatch",
                 "parts must be a non-empty mapping part_id -> member output keys")
        assigned = {}
        for part_id, keys in parts.items():
            for key in keys:
                _require(key not in assigned, "part_coverage_mismatch",
                         f"{key}: two parts claim the same member")
                assigned[key] = part_id
        for member in record["members"]:
            _require(member["output_key"] in assigned, "part_coverage_mismatch",
                     f"{member['output_key']}: no source part claims this member")
            member["part_id"] = assigned[member["output_key"]]
    return _annotated(replacement, record, project=project)


def carry_schematic_refinement(previous: ModuleInstance, replacement: ModuleInstance, *,
                               project: ProjectRevision | None = None) -> ModuleInstance:
    """Preserve a structurally checked record; never derive a new source from a generator's loose metadata."""
    record = _record(previous, project=project)
    _instance(replacement)
    _require((previous.key, previous.module_key, previous.module_digest)
             == (replacement.key, replacement.module_key, replacement.module_digest),
             "refinement_owner_changed", "carry cannot change instance or definition ownership")
    _roles(replacement, record["members"], project=project)
    return _annotated(replacement, record, project=project)


def _live_source(project, reference):
    """Where THAT SAME source output lives IN THIS revision. Or why it is not here."""
    key = reference.get(_LIVE_ADDRESS)
    if key is None:
        return {"present": False, "why": "record carries no live address (schema /1 or historical-only)"}
    owner = next((item for item in project.instances if item.key == key), None)
    output = next((item for item in owner.outputs if item.key == reference["output_key"]),
                  None) if owner else None
    _require(output is not None, "source_binding_mismatch",
             f"{key}: the declared live source address is absent from this revision")
    _require(_hash(output.to_dict()) == reference["output_digest"], "live_source_changed",
             f"{key}: the live source payload differs from the pinned one; "
             "the section was derived from another shape")
    return {"present": True, "instance_key": key,
            "op_id": output_id(project.project_id, key, reference["output_key"]),
            "payload": "identical_to_pinned_digest"}


def adopt_foreign_members(instance: ModuleInstance, project: ProjectRevision | None, *,
                          members: Sequence[Mapping[str, str]], part_id: str) -> ModuleInstance:
    """Take under lineage descendants that live in a SEPARATE instance of the same project.

    🔴 WHY. Two `create_wall_type` calls from the example section live in
    `section-types`, and this is visible by instrument: the section program
    has 23 ops, the record addressed 21, and two were UNADDRESSABLE. The
    types cannot be relocated to the walls — their separateness is itself the
    author's decision (one type shared by all walls). So the address must be
    able to cross the instance boundary, and this is done in ONE explicit
    move, not by patching the dict in place: the record is reread in full
    after the edit, and the role of every new member is checked against the
    registry contract.

    New members are placed into THEIR OWN source part: they are not
    descendants of the atrium or the facade, they are decisions that serve
    the whole section, and attributing them to a foreign part would mean
    lying about their origin.

    `project=None` means adoption BEFORE the revision is assembled (the
    foreign outputs do not yet exist in any snapshot): structure is checked,
    and membership will be checked by the very first `refinement_view` on the
    finished revision. There is no silent "take it on faith" here: without
    this kind of check, the record would not be readable at all.
    """
    record = _thaw(_record(instance, project=project))
    _require(record["schema"] in _SCHEMAS, "unsupported_refinement_schema", "unknown record schema")
    _key(part_id, "part_id")
    known = {(m.get("instance_key"), m["output_key"]) for m in record["members"]}
    added = []
    for member in members:
        _require(isinstance(member, Mapping) and set(member) >= {"instance_key", "output_key", "role"},
                 "member_coverage_mismatch", "foreign member needs instance_key/output_key/role")
        address = (member["instance_key"], member["output_key"])
        _require(address not in known, "member_coverage_mismatch",
                 f"{member['output_key']}: this address is already a member")
        known.add(address)
        added.append({"output_key": member["output_key"], "role": member["role"],
                      "instance_key": member["instance_key"], "part_id": part_id})
    _require(added, "member_coverage_mismatch", "nothing to adopt")
    record["schema"] = REFINEMENT_SCHEMA_V2
    named = [member for member in record["members"] if "part_id" in member]
    if named and len(named) != len(record["members"]):
        raise RefinementError("part_coverage_mismatch", "half-marked members cannot adopt")
    if not named:
        # Record `/1` had no parts: former members are given ONE explicit
        # part, named by the source output's key — exactly what the view
        # printed before, only now said out loud.
        for member in record["members"]:
            member["part_id"] = record["source"]["output_key"]
    record["members"] = [*record["members"], *added]
    result = replace(instance, metadata={**_thaw(instance.metadata), "refinement": record})
    _record(result, project=project)
    return result


def refinement_view(project: ProjectRevision, instance_key: str, *, source: ProjectRevision) -> dict:
    """Detached report over exact supplied snapshots, not serialized geometry/native evidence."""
    _project(project)
    _project(source)
    instance = next((item for item in project.instances if item.key == instance_key), None)
    _require(instance is not None, "invalid_refinement", "target instance does not exist")
    record = _record(instance, project=project)
    reference = record["source"]
    _require(reference["project_id"] == project.project_id == source.project_id
             and reference["revision_id"] == source.revision_id,
             "source_binding_mismatch", "exact source project/revision differs")
    output = _source_output(source, reference["instance_key"], reference["output_key"])
    _require(_hash(output.to_dict()) == reference["output_digest"], "source_binding_mismatch", "source output payload differs")
    _require(source.ir_version == project.ir_version == spec.IR_VERSION,
             "unsupported_refinement_ir", "role contracts only qualify the current IR version")
    instances = {item.key: item for item in project.instances}
    own = [member for member in record["members"] if "instance_key" not in member]
    rows = [{**member, "op_id": output_id(project.project_id, instance.key, member["output_key"]),
             "output_digest": _hash(item.to_dict())}
            for member, item in zip(own, instance.outputs, strict=True)]
    for member in record["members"]:
        if "instance_key" not in member:
            continue
        owner = instances.get(member["instance_key"])
        item = next((x for x in owner.outputs if x.key == member["output_key"]), None) if owner else None
        _require(item is not None, "member_coverage_mismatch",
                 f"{member['output_key']}: foreign member is absent from this revision")
        rows.append({**member,
                     "op_id": output_id(project.project_id, member["instance_key"], member["output_key"]),
                     "output_digest": _hash(item.to_dict())})
    lineage = {}
    for row in rows:
        lineage.setdefault(row.get("part_id", reference["output_key"]), []).append(row["op_id"])
    return {"schema": "kir-schematic-refinement-view/1", "project_id": project.project_id,
        "target_revision_id": project.revision_id, "target_instance_key": instance.key,
        "source": record["source"], "source_op_id": output_id(source.project_id,
            reference["instance_key"], reference["output_key"]),
        # The live address is stated IN THE VIEW and IS CHECKED: the same
        # output must be found at it in THIS revision and must carry THE SAME
        # payload. Otherwise the "live source" would be a promise, not an
        # address.
        "live_source": _live_source(project, reference),
        "members": rows,
        # `lineage` is the SOURCE side: part -> its descendants. In record
        # `/1` there is one part, named by the source output's key: it is not
        # invented, it honestly says "there is no breakdown, one source for
        # everyone."
        "lineage": {part: sorted(ids) for part, ids in lineage.items()},
        "losses": record["losses"], "inactive_parameters": record["inactive_parameters"],
        "binding_status": "exact_supplied_source", "ancestry": "not_checked",
        "roles_and_losses": "authored_assertions", "loss_inventory": "not_proven_exhaustive",
        "geometry_preservation": "not_claimed", "recipe_execution": "not_run",
        "compiler_validation": "not_run", "native_execution": "not_run"}


# ─── C2: source edit -> three sets, remainder, deviation, questions ────
#
# 🔴 WHAT IS NOT DONE HERE. No operation is "recognized": what counts as the
# atrium and what counts as the facade is stated BY THE AUTHOR — via source
# parts (`part_id`) and the edit kind (`change["kind"]`). No body is built or
# judged here: the deviation and remainder numbers come from
# `kir.refine.deviation`, and if they are absent — this is NAMED, not
# replaced with zero (rule 1 of the B2↔C2 contract: `coverage is None` is
# NOT zero).

REFINEMENT_REPORT_SCHEMA = "kir-refinement-report/1"
QUESTION_SCHEMA = "kir-refinement-question/1"

#: The kinds of source edit this contract knows how to apply to a section.
#: The list is CLOSED on purpose: an unknown kind must refuse by name, not
#: silently return "nothing changed" — silence here reads as "the edit
#: affects nothing," and that is the worst possible untruth.
_CHANGE_KINDS = ("atrium_contour", "facade_curve")

#: The facade sides the edit language KNOWS. The default is `min_y`: exactly
#: what every previous edit did, so none of them moves.
_FACADE_SIDES = ("min_y", "max_y")

#: 🔴 AN UNDECLARED KEY WAS SWALLOWED SILENTLY. Measurement 07.09.2026:
#: `{"kind": "facade_curve", "outer_dy_mm": -800, "side": "north"}` was
#: accepted and produced exactly the same delta as an edit of the SOUTH
#: edge, with zero bounds checks — meaning the author asked for one side,
#: got another, and never found out. The list is closed by kind: the atrium
#: has no side at all, and "allow it for now" here would mean the product is
#: guessing on the language's behalf.
_CHANGE_KEYS = {"atrium_contour": frozenset({"kind", "hole_mm", "why"}),
                "facade_curve": frozenset({"kind", "outer_dy_mm", "why", "side"})}


def _change_side(change) -> str:
    """The facade side from the edit: the declared one, else a named refusal."""
    side = change.get("side", _FACADE_SIDES[0])
    _require(side in _FACADE_SIDES, "facade_side_unsupported",
             f"{side!r}: язык правок знает стороны {', '.join(_FACADE_SIDES)}; "
             "иная сторона фасада этим словарём не выражается, и делать вид, "
             "что выражается, значило бы подменить сторону молча")
    return side


def _checked_change(change):
    """The edit's keys come from the closed list for its KIND. Anything else is a refusal by name."""
    kind = change.get("kind")
    _require(kind in _CHANGE_KINDS, "unsupported_change_kind",
             f"{kind!r}: this contract applies {', '.join(_CHANGE_KINDS)} only")
    extra = sorted(set(change) - _CHANGE_KEYS[kind])
    _require(not extra, "unsupported_change_key",
             f"{', '.join(repr(key) for key in extra)}: род {kind!r} объявляет ключи "
             f"{', '.join(sorted(_CHANGE_KEYS[kind]))}; необъявленный ключ здесь "
             "молча ничего не делает, а автор считает, что попросил")
    return kind, (_change_side(change) if kind == "facade_curve" else None)


@dataclass(frozen=True)
class Question:
    """A question TO THE HUMAN. The choice is theirs; this carries only the address, the options, and the reasoning."""

    question_id: str
    address: str
    choices: tuple
    why: str

    def to_dict(self) -> dict:
        return {"schema": QUESTION_SCHEMA, "question_id": self.question_id,
                "address": self.address, "choices": list(self.choices), "why": self.why}


@dataclass(frozen=True)
class RefinementReport:
    """Three DISJOINT sets and what they were obtained by.

    The sum of the three sets equals ALL outputs of the refined instance.
    Without that equality, an output could disappear silently: not
    recomputed, not preserved, not requiring a decision — that is, simply
    nothing said about it at all.
    """

    revision_before: str
    source_output_id: str
    recomputed: tuple
    preserved: tuple
    needs_decision: tuple
    residue: tuple
    deviation: dict
    lineage: dict
    decisions_digest: str
    questions: tuple
    analysis_limits: tuple
    revision_after: str | None = None
    #: Contour connectivity AFTER the edit: how many ends were left unpaired
    #: and how many closed regions the wall axes form (by level). Appended at
    #: the tail with a default value — old readers are untouched.
    #: `closed_loops: None` means "nothing to count with" (no shapely), not "zero."
    connectivity: dict = field(default_factory=lambda: {"loose_ends": 0, "closed_loops": None})

    @property
    def questions_left(self) -> int:
        """How many questions remain. A property, so the number cannot drift from the list."""
        return len(self.questions)

    def to_dict(self) -> dict:
        return {"schema": REFINEMENT_REPORT_SCHEMA,
                "revision_before": self.revision_before, "revision_after": self.revision_after,
                "source_output_id": self.source_output_id,
                "recomputed": list(self.recomputed), "preserved": list(self.preserved),
                "needs_decision": list(self.needs_decision),
                "residue": [dict(row) for row in self.residue], "deviation": dict(self.deviation),
                "lineage": {key: list(value) for key, value in self.lineage.items()},
                "decisions_digest": self.decisions_digest,
                "questions": [q.to_dict() for q in self.questions],
                #: How many questions remain FOR THIS report. The number is
                #: printed next to the list on purpose: a reader who counts
                #: the questions themselves will sooner or later count them
                #: on a different basis.
                "questions_left": len(self.questions),
                "analysis_limits": list(self.analysis_limits),
                "connectivity": dict(self.connectivity)}


def _rect(value, name):
    try:
        (x0, y0), (x1, y1) = value
        box = (float(x0), float(y0)), (float(x1), float(y1))
    except (TypeError, ValueError) as exc:
        raise RefinementError("invalid_change", f"{name}: expected [[x0,y0],[x1,y1]]") from exc
    _require(box[1][0] > box[0][0] and box[1][1] > box[0][1], "invalid_change",
             f"{name}: empty rectangle")
    return box


def _poly(box):
    (x0, y0), (x1, y1) = box
    return {"shape": "poly", "points_mm": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def _bounds(points):
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return (min(xs), min(ys)), (max(xs), max(ys))


def _point(value):
    return round(float(value[0]), 6), round(float(value[1]), 6)


def _level_key(op):
    return _canonical(op.get("level"))


def _on_axis(point, wall) -> bool:
    """Whether a point lies ON a wall's axis without coinciding with its end (a T-junction)."""
    px, py = _point(point)
    (x0, y0), (x1, y1) = _point(wall["p0_mm"]), _point(wall["p1_mm"])
    if (px, py) in ((x0, y0), (x1, y1)):
        return False
    cross = (x1 - x0) * (py - y0) - (y1 - y0) * (px - x0)
    if abs(cross) > 1e-6:
        return False
    dot = (px - x0) * (x1 - x0) + (py - y0) * (y1 - y0)
    length2 = (x1 - x0) ** 2 + (y1 - y0) ** 2
    return length2 > 0.0 and -1e-6 <= dot <= length2 + 1e-6


def _facade_base(ops, side: str = "min_y") -> dict:
    """The elevation of the CURRENT facade edge — by level, from the floor contours.

    🔴 THE LITERAL `y == 0` HELD FOR EXACTLY ONE EDIT. Review 6 measurement:
    a second facade edit by -800 moved the floor contour (to -1600) and did
    NOT move the walls — they were already at -800, and the facade was
    recognized by zero. The slab drifted out from under the walls, and the
    report called the walls PRESERVED. The edge is taken from the very
    geometry that moves: the minimum `y` of the floor's outer contour at
    ITS OWN level.
    """
    pick = min if side == "min_y" else max
    bases, everything = {}, []
    for op in ops:
        if op.get("op") != "create_floor_by_contour":
            continue
        ys = [float(point[1]) for point in op["contour"]["outer"]["points_mm"]]
        if not ys:
            continue
        everything.extend(ys)
        bases[_level_key(op)] = pick(pick(ys), bases.get(_level_key(op), pick(ys)))
    bases["*"] = pick(everything) if everything else 0.0
    return bases


def _distance_to_segment(point, start, end) -> float:
    (px, py), (x0, y0), (x1, y1) = point, start, end
    dx, dy = x1 - x0, y1 - y0
    length2 = dx * dx + dy * dy
    if length2 <= 0.0:
        return math.hypot(px - x0, py - y0)
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _slab_edges_without_walls(ops, tolerance: float = 1.0):
    """Edges of the floor's outer contour under which there is NO wall of its own level.

    🔴 CONNECTIVITY IS NOT ONLY WALLS WITH EACH OTHER. The earlier instruments
    (`_free_ends`, `_closed_loops`) walked only `create_wall`, and a
    divergence between the slab and the wall was inexpressible to them BY
    CONSTRUCTION: both quantities stayed at 0 and 3 while the floor drifted
    800 mm out from under the facade. Here a third question is asked: does a
    slab edge lie on a wall (both endpoints of the edge no farther than the
    tolerance from the axis of a wall at the same level).
    """
    walls = {}
    for op in ops:
        if op.get("op") == "create_wall":
            walls.setdefault(_level_key(op), []).append(op)
    missing = []
    for op in ops:
        if op.get("op") != "create_floor_by_contour":
            continue
        points = [_point(p) for p in op["contour"]["outer"]["points_mm"]]
        level = walls.get(_level_key(op), [])
        for index, start in enumerate(points):
            end = points[(index + 1) % len(points)]
            if start == end:
                continue
            covered = any(
                _distance_to_segment(start, _point(wall["p0_mm"]), _point(wall["p1_mm"]))
                <= tolerance
                and _distance_to_segment(end, _point(wall["p0_mm"]), _point(wall["p1_mm"]))
                <= tolerance
                for wall in level)
            if not covered:
                missing.append((op["id"], start, end))
    return tuple(missing)


def _facade_connectivity(ops, side: str = "min_y"):
    """Who moves with the facade, who follows it by a CORNER, and who is left hanging.

    🔴 WHY A CORNER IS AN EXPRESSED LINK AND A T-JUNCTION IS NOT. Owner's
    measurement, 07.09.2026: the edit `outer_dy_mm=-800` moved ONLY the
    facade wall, the ends of the adjoining walls stayed in place — the
    contour went from closed (3 regions, 0 free ends) to torn (0 regions, 12
    free ends), while the report meanwhile said
    `recomputed 6 · preserved 17 · needs_decision 0`, that is, it declared
    the torn walls PRESERVED.

    Coinciding ends at ONE level is a fact checkable by a number: two walls
    meet at a corner, and moving the facade drags that corner along. There is
    no author's choice here: the other outcome ("the wall stayed, an 800 mm
    gap opened between it and the facade") is not a second version of the
    design, it is a tear.

    A T-junction (a wall's end lies ON the facade's axis but not at its
    corner) is a different matter: stretching the partition to the new
    facade or leaving it shorter is a DECISION, and the link is not expressed
    by the language. Such a wall goes into `needs_decision` with a question,
    not into `preserved`.
    """
    walls = [op for op in ops if op.get("op") == "create_wall"]
    bases = _facade_base(ops, side)
    moved = []
    for op in walls:
        base = bases.get(_level_key(op), bases["*"])
        if abs(float(op["p0_mm"][1]) - base) <= 1e-6 and \
                abs(float(op["p1_mm"][1]) - base) <= 1e-6:
            moved.append(op)
    moved_ids = {op["id"] for op in moved}
    corners = set()
    for op in moved:
        for point in (op["p0_mm"], op["p1_mm"]):
            corners.add((_level_key(op), _point(point)))
    follow, hanging = {}, []
    for op in walls:
        if op["id"] in moved_ids:
            continue
        level = _level_key(op)
        ends = tuple(index for index, name in enumerate(("p0_mm", "p1_mm"))
                     if (level, _point(op[name])) in corners)
        if ends:
            follow[op["id"]] = ends
            continue
        if any(_on_axis(op[name], other) for name in ("p0_mm", "p1_mm")
               for other in moved if _level_key(other) == level):
            hanging.append(op["id"])
    return moved_ids, follow, tuple(sorted(hanging))


def _free_ends(ops):
    """Wall ends that no other wall meets AT THE SAME LEVEL.

    The level matters here: the section's three floors stand on the same
    axes in plan, and the point (0,0) occurs on three walls of DIFFERENT
    levels. Counting without the level would declare connected walls that
    never actually met.
    """
    seen = {}
    for op in ops:
        if op.get("op") != "create_wall":
            continue
        for name in ("p0_mm", "p1_mm"):
            seen.setdefault((_level_key(op), _point(op[name])), []).append(op["id"])
    return tuple(sorted((key, tuple(sorted(ids)))
                        for key, ids in seen.items() if len(ids) < 2))


def _closed_loops(ops):
    """Closed regions by level. `None` means there is nothing to count with, and that is NOT zero."""
    try:
        from shapely.geometry import LineString
        from shapely.ops import polygonize, unary_union
    except Exception:  # noqa: BLE001
        return None
    levels = {}
    for op in ops:
        if op.get("op") == "create_wall":
            levels.setdefault(_level_key(op), []).append(op)
    total = 0
    for walls in levels.values():
        lines = [LineString([tuple(op["p0_mm"])[:2], tuple(op["p1_mm"])[:2]]) for op in walls]
        total += len(list(polygonize(unary_union(lines))))
    return total


#: Options and reasoning — BY THE QUESTION'S KIND. One list for both kinds
#: would offer the author "trim the atrium" in a place where there is no
#: atrium in the edit at all.
_CHOICES = {
    "atrium": ("move_wall_to_new_atrium_edge", "keep_wall_and_shrink_atrium",
               "split_wall_around_the_opening"),
    "facade": ("stretch_the_wall_to_the_new_facade", "keep_the_wall_and_accept_the_gap"),
    "slab": ("move_the_wall_onto_the_new_slab_edge", "keep_the_wall_and_trim_the_slab"),
}
_WHY = {
    "atrium": ("новый контур атриума пересекает ось этой стены; чем стала стена — "
               "из геометрии не следует, это проектное решение"),
    "facade": ("конец этой стены примыкал к оси фасада не углом, а посередине; "
               "связь языком не выражена, и тянуть её за фасадом или оставить "
               "короче — решение автора"),
    "slab": ("ребро этой плиты после правки осталось без стены: пол уехал из-под "
             "фасада. Куда идти — стене за плитой или плите к стене — решает автор"),
}


def _hole_edges(hole):
    """Read CONTOUR without changing its authored shape/arc/anchor payload."""
    from kir.contour import validate_region

    diagnostics = []
    try:
        region = validate_region({"outer": _thaw(hole)}, [], None, "hole", diagnostics)
    except Exception as exc:
        raise RefinementError("hole_geometry_unavailable",
                              f"cannot read the authored hole: {type(exc).__name__}") from exc
    _require(region is not None, "hole_geometry_unavailable",
             "hole geometry is invalid or needs unresolved anchors; no opening was changed")
    return region["outer"]


def _hole_index(holes, box):
    """Which of the existing openings this edit addresses. No guessing.

    🔴 THE WHOLE LIST CANNOT BE REPLACED. The previous edition wrote
    `contour["holes"] = [new hole]`, meaning an atrium edit ERASED every
    other floor opening (measurement: the stair shaft disappeared from all
    three floors). The addressed opening is the one the new hole
    INTERSECTS; if there are several, that is not our choice to make, and
    the refusal is named.
    """
    if not holes:
        return None
    from kir.contour import edges_are_straight, edges_bbox, edges_vertices, is_spline

    try:
        from shapely.geometry import Polygon, box as rectangle
    except ImportError as exc:
        raise RefinementError("hole_geometry_unavailable", "shapely is unavailable") from exc

    patch = rectangle(*box[0], *box[1])
    hits = []
    for index, hole in enumerate(holes):
        edges = _hole_edges(hole)
        _require(not any(is_spline(edge[2]) for edge in edges), "ambiguous_hole_address",
                 "a spline hole has no exact offline bounds; identify the opening explicitly")
        # Exact line/arc bounds can EXCLUDE a neighbour, never prove a hit.
        if not rectangle(*edges_bbox(edges)).intersects(patch):
            continue
        _require(edges_are_straight(edges), "ambiguous_hole_address",
                 "a curved hole overlaps the requested bounds; exact addressing is unavailable")
        if Polygon(edges_vertices(edges)).intersects(patch):
            hits.append(index)
    if len(hits) > 1:
        raise RefinementError(
            "ambiguous_hole_address",
            f"новый контур пересекает {len(hits)} существующих отверстия; "
            "какое из них правится — решение автора, а не догадка")
    return hits[0] if hits else None


def _replace_atrium_hole(contour, requested, replacement):
    """Both authoring paths edit the ring addressed by the ORIGINAL request.

    Shrinking must not select again by the smaller result: another candidate
    outside that result still makes the original request ambiguous. Every
    non-addressed shape stays in its original slot, with its literal payload.
    """
    contour = _thaw(contour)
    existing = list(contour.get("holes") or ())
    index = _hole_index(existing, requested)
    outer = _bounds(contour["outer"]["points_mm"])
    clipped = ((max(replacement[0][0], outer[0][0]), max(replacement[0][1], outer[0][1])),
               (min(replacement[1][0], outer[1][0]), min(replacement[1][1], outer[1][1])))
    clipped = _rect(clipped, "clipped atrium")
    if index is None:
        existing.append(_poly(clipped))
    else:
        existing[index] = _poly(clipped)
    contour["holes"] = existing
    return contour


#: Op -> its ABSOLUTE points, which must travel together with the host.
#: Only kinds addressed by coordinates are here. A window and a door are NOT
#: included on purpose: their place is given by `offset_mm` along the host's
#: axis, and they travel on their own behind a moved wall — including them
#: would mean moving them twice.
_HOSTED_ABSOLUTE = {"create_opening": ("p0_mm", "p1_mm")}


def _host_ref(op):
    """An op's host is ONLY a declared reference `{by: ref}`. Otherwise there is no host."""
    host = op.get("host")
    if isinstance(host, Mapping) and host.get("by") == "ref":
        return str(host.get("value"))
    return None


def _hosted_parts_left_behind(ops, change):
    """Parts whose host is moving while they themselves cannot follow. A limit, not a zero."""
    if change.get("kind") != "facade_curve":
        return ()
    moved_ids, follow, _hanging = _facade_connectivity(ops, _change_side(change))
    left = []
    for op in ops:
        host = _host_ref(op)
        if host is None:
            continue
        # 🔴 SKIPPING BY THE OP'S NAME MEANS SKIPPING SOMEONE WHO WAS NOT
        # MOVED. `create_opening` of kind `host_face` sits in the same table
        # but CARRIES `outline`/`contour`, not `p0_mm`/`p1_mm`, and the edit
        # does not touch it. Skipping by name would declare it moved even
        # though it stayed put. What is asked is exactly what moved: whether
        # the op has even one of the listed parameters.
        moved_here = (host in moved_ids
                      and any(param in op for param in _HOSTED_ABSOLUTE.get(op.get("op"), ())))
        if moved_here:
            continue
        if host in moved_ids or host in follow:
            left.append(op["id"])
    return tuple(sorted(left))


#: A refusal code and action: the half-width is DECLARED by the wall type, not by us.
_GAP_CODE = "wall_type_required_for_gap"
_GAP_ACTION = ("зазор между атриумом и телом стены недоказуем: стена не ссылается на "
               "`create_wall_type` с объявленными `layers`. Действие: объяви тип стены "
               "(`create_wall_type.layers`) и повтори ответ — придумать половину ширины "
               "за автора значило бы выдать выдуманную геометрию за проектную")


def _walls_without_declared_gap(ops, addresses):
    """Of the addresses, those whose half-width NO type declares.

    🔴 AN ENDLESS QUESTION. R2 measurement, 07.09.2026, on the apartment
    building RIGHT AFTER refinement: `_wall_half_width` -> `None`,
    `_shrunk_atrium` cut EXACTLY to the axis, `_still_open` counted touching
    as intersecting — 3 asked, 3 answered, 3 open forever, and the question's
    reason named the wrong thing ("the contour still touches this axis").
    What is asked is what is actually missing.
    """
    program = {"ops": list(ops)}
    by_id = {op["id"]: op for op in ops}
    out = []
    for address in addresses:
        wall = by_id.get(str(address))
        if wall is None or wall.get("op") != "create_wall":
            continue
        if _wall_half_width(wall, program) is None:
            out.append(str(address))
    return tuple(sorted(out))


def _stale_decisions(ops, decisions):
    """Accepted decisions whose geometry HAS MOVED OUT FROM UNDER THEM. Answered by shapely, not by eye.

    🔴 A DECISION WAS COUNTED AS APPLIED TO A WALL THAT NO LONGER EXISTS. The
    answer `keep_wall_and_shrink_atrium` is a contract between a HOLE and the
    AXIS of a specific wall. The wall is later removed or moved by the next
    change, and the contract is left dangling: the remainder keeps naming a
    615 mm setback at an address that no longer exists, and the question is
    never asked again. What is asked here is exactly what the decision was
    about: does that wall still exist, and does the trimmed hole hold the
    declared clearance to its axis.

    Returns `(vanished, violated)`: the first have nothing left to decide (no
    address — that is a limit), the second go back into `needs_decision`.
    """
    rows = list(_thaw(decisions) or ())
    if not rows:
        return (), ()
    by_id = {op["id"]: op for op in ops}
    try:
        from shapely.geometry import LineString, box as _box
    except Exception:  # noqa: BLE001 — the library is absent: this is a limit, not an answer
        return tuple(sorted({str(row["address"]) for row in rows
                             if str(row["address"]) not in by_id})), ()
    missing, violated = set(), set()
    for row in rows:
        address = str(row["address"])
        wall = by_id.get(address)
        if wall is None or wall.get("op") != "create_wall":
            missing.add(address)
            continue
        try:
            applied = _rect(row.get("applied_mm"), "decision.applied_mm")
        except RefinementError:
            missing.add(address)
            continue
        axis = LineString([tuple(wall["p0_mm"])[:2], tuple(wall["p1_mm"])[:2]])
        if _box(applied[0][0], applied[0][1], applied[1][0], applied[1][1]).intersects(axis):
            violated.add(address)
    return tuple(sorted(missing)), tuple(sorted(violated))


def _changed_ops(ops, change):
    """A SOURCE edit, translated onto the section's declared contours.

    🔴 THIS IS NOT A RECIPE RECOMPUTE, AND IT ISN'T PASSED OFF AS ONE. The
    section's recipe is sealed (`sealed_evaluation`), and calling it from here
    would mean changing someone else's subject. Here, by the edit's declared
    kind, the AUTHOR-DECLARED numbers change — a hole's contour or the
    facade face's elevation — and the operation payloads are then compared
    before and after. What did not change did not change; what changed is
    named explicitly.
    """
    kind, side = _checked_change(change)
    out = []
    if kind == "atrium_contour":
        hole = _rect(change.get("hole_mm"), "change.hole_mm")
        for op in ops:
            if op.get("op") != "create_floor_by_contour":
                out.append(op)
                continue
            contour = _replace_atrium_hole(op["contour"], hole, hole)
            out.append({**_thaw(op), "contour": contour})
        return out
    dy = float(change.get("outer_dy_mm", 0.0))
    _require(dy != 0.0, "invalid_change", "facade_curve needs a nonzero outer_dy_mm")
    moved_ids, follow, _hanging = _facade_connectivity(ops, side)
    bases = _facade_base(ops, side)
    for op in ops:
        name = op.get("op")
        if name in _HOSTED_ABSOLUTE and _host_ref(op) in moved_ids:
            # 🔴 AN OPENING STAYED WHERE ITS HOST NO LONGER IS. `create_opening`
            # of kind `wall_rect` is addressed by ABSOLUTE points (unlike a
            # window or door, which sit at `offset_mm` ALONG the wall and
            # travel with it on their own). A facade edit moved the wall and
            # did not move the opening, and the report called the opening
            # PRESERVED: three edits in a row carried the host 1500 mm away,
            # and all three times the opening was counted as intact.
            moved = _thaw(op)
            for param in _HOSTED_ABSOLUTE[name]:
                point = moved.get(param)
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    moved[param] = [point[0], float(point[1]) + dy, *list(point)[2:]]
            out.append(moved)
        elif name == "create_floor_by_contour":
            contour = _thaw(op["contour"])
            outer = contour["outer"]["points_mm"]
            base = bases.get(_level_key(op), bases["*"])
            contour["outer"]["points_mm"] = [
                [point[0], point[1] + dy] if float(point[1]) == base else list(point)
                for point in outer]
            out.append({**_thaw(op), "contour": contour})
        elif name == "create_wall":
            p0, p1 = list(op["p0_mm"]), list(op["p1_mm"])
            if op["id"] in moved_ids:
                p0, p1 = [p0[0], p0[1] + dy], [p1[0], p1[1] + dy]
                out.append({**_thaw(op), "p0_mm": p0, "p1_mm": p1})
            elif op["id"] in follow:
                # The corner is DRAGGED ALONG: exactly the end that met the
                # facade wall's end at the same level moves. The other end
                # stays put.
                ends = follow[op["id"]]
                if 0 in ends:
                    p0 = [p0[0], p0[1] + dy]
                if 1 in ends:
                    p1 = [p1[0], p1[1] + dy]
                out.append({**_thaw(op), "p0_mm": p0, "p1_mm": p1})
            else:
                out.append(op)
        else:
            out.append(op)
    return out


def _walls_touched(ops, change):
    """Wall axes that a new hole TOUCHES. Answered by `shapely`, not by eye."""
    if change.get("kind") != "atrium_contour":
        return []
    try:
        from shapely.geometry import LineString, box as _box
    except Exception:  # noqa: BLE001 — the library is absent: this is a limit, not an answer
        return None
    hole = _rect(change.get("hole_mm"), "change.hole_mm")
    patch = _box(hole[0][0], hole[0][1], hole[1][0], hole[1][1])
    hit = []
    for op in ops:
        if op.get("op") != "create_wall":
            continue
        if LineString([tuple(op["p0_mm"]), tuple(op["p1_mm"])]).intersects(patch):
            hit.append(op["id"])
    return sorted(hit)


def _section_instance(project, source_output_id):
    """The instance whose record names THIS source. Otherwise, a refusal by name."""
    for instance in project.instances:
        record = _thaw(instance.metadata.get("refinement")) if instance.metadata else None
        if not isinstance(record, dict) or "source" not in record:
            continue
        reference = record["source"]
        live = reference.get(_LIVE_ADDRESS, reference.get("instance_key"))
        if output_id(reference["project_id"], live, reference["output_key"]) == source_output_id:
            return instance, record
        if output_id(reference["project_id"], reference["instance_key"],
                     reference["output_key"]) == source_output_id:
            return instance, record
    raise RefinementError("unknown_refinement_source",
                          f"{str(source_output_id)[:12]}: no instance declares this source")


def _deviation_of(before_ops, after_ops):
    """Shape deviation is a NUMBER from the neighboring instrument, not a flag or our own guess.

    Rule 3 of the B2↔C2 contract: refusal ≠ zero. If `plan_area_delta`
    refused, or `shapely` is absent, the measure is NAMED empty, and this is
    visible in `analysis_limits`.
    """
    try:
        from kir.refine.deviation import plan_area_delta
    except Exception as exc:  # noqa: BLE001
        return {"measure": None, "value": None, "unit": None}, [
            f"deviation not measured: {type(exc).__name__}"]
    try:
        deltas, problems = plan_area_delta(before_ops, after_ops)
    except Exception as exc:  # noqa: BLE001 — the instrument's refusal is named, not silent
        return {"measure": None, "value": None, "unit": None}, [
            f"plan_area_delta failed: {type(exc).__name__}: {exc}"]
    limits = [f"plan_area_delta: {row}" for row in (problems or ())]
    if not deltas:
        return {"measure": None, "value": None, "unit": None}, limits + [
            "plan_area_delta returned no floor"]
    # The key is a reference to the LEVEL (a floor operation's id is a digest
    # of its payload and changes with a contour edit; the level is untouched
    # by the edit). The order is sorted, so a second process yields the same
    # bytes.
    return {"measure": "plan_area_delta_mm2", "unit": "mm2",
            "value": [float(deltas[key]) for key in sorted(deltas)],
            "by_level": {key: float(deltas[key]) for key in sorted(deltas)}}, limits


#: 🔴 A SUM ADDED UP FROM STEPS IS BLIND TO WHAT HAPPENED BETWEEN THEM.
#: Measurement 07.09.2026: three edits gave steps of 11.2 / 5.6 / -5 million
#: mm², and only the reader ever added them up. A manual edit between the
#: steps (a foreign shaft, -1 million mm² per floor) does not enter that sum
#: at all. So on the FIRST edit, the instance's passport records the BASE
#: (the R0 state numbers), and each time the sum is MEASURED as the
#: difference from it.
#: ⚠️ This key is LOAD-BEARING: it is read by `_total_of` and written by
#: `record_pending_change`, `apply_source_change`, `answer_question`. Its
#: place in `_LOAD_BEARING_METADATA` (`kir/project_merge.py`) is entered by
#: that file's owner.
_BASELINE_KEY = "refinement_baseline"
_BASELINE_SCHEMA = "kir-refinement-baseline/1"


def _measure_state(ops):
    """State numbers: plan area by level, op count, volume. A refusal is named."""
    from kir.refine.deviation import plan_areas, section_volume_mm3

    limits = []
    try:
        areas, problems = plan_areas(ops)
    except Exception as exc:  # noqa: BLE001 — the instrument's refusal is named, not silent
        areas, problems = {}, []
        limits.append(f"plan_areas failed: {type(exc).__name__}: {exc}")
    limits.extend(f"plan_areas: {row}" for row in (problems or ()))
    volume, volume_limits = section_volume_mm3(ops)
    limits.extend(volume_limits)
    return ({key: float(value) for key, value in sorted(areas.items())},
            len(list(ops)), volume, limits)


def _baseline_row(project, instance, ops, source_op_id):
    """The R0 base for this instance. Once recorded, it is NOT overwritten."""
    stored = _thaw(instance.metadata.get(_BASELINE_KEY)) if instance.metadata else None
    if isinstance(stored, dict) and stored.get("schema") == _BASELINE_SCHEMA:
        return stored, False
    areas, op_count, volume, limits = _measure_state(ops)
    return {"schema": _BASELINE_SCHEMA, "revision_id": project.revision_id,
            "source_output_id": str(source_op_id), "plan_area_by_level": areas,
            "op_count": op_count, "volume_mm3": volume, "limits": limits}, True


def _total_of(baseline, after_ops, source_op_id):
    """The sum FROM R0: the measured difference between the base and the state AFTER this edit."""
    areas, op_count, volume, limits = _measure_state(after_ops)
    base_areas = dict(baseline.get("plan_area_by_level") or {})
    by_level, missing = {}, []
    for level in sorted(set(base_areas) | set(areas)):
        if level not in base_areas or level not in areas:
            missing.append(level)
            continue
        by_level[level] = float(areas[level]) - float(base_areas[level])
    if missing:
        limits.append("total: level present on one side only: "
                      f"{len(missing)} ({', '.join(str(x)[:12] for x in missing)})")
    base_volume = baseline.get("volume_mm3")
    return {"measure": "plan_area_delta_mm2" if by_level else None, "unit": "mm2",
            "value": [by_level[key] for key in sorted(by_level)],
            "by_level": by_level,
            "source_output_id": str(source_op_id),
            "baseline_revision": baseline.get("revision_id"),
            "op_count": {"baseline": int(baseline.get("op_count") or 0), "now": op_count,
                         "delta": op_count - int(baseline.get("op_count") or 0)},
            "volume_mm3": volume, "baseline_volume_mm3": base_volume,
            "volume_delta_mm3": (None if volume is None or base_volume is None
                                 else volume - base_volume),
            "limits": tuple(limits)}


def _residue_of(record, source_op_id, limits, decisions=()):
    """The remainder of what was not carried over — a number WITH AN ADDRESS.

    The source of the rows is the author-declared losses (`losses`) and
    inactive parameters: this is exactly what refinement did NOT carry over,
    and it was declared before any measurement. Volume numbers are placed
    here by B2 when bodies exist; their absence is named, not replaced with
    zero.
    """
    rows = []
    for name in record.get("losses", ()):
        rows.append({"address": source_op_id, "what": name, "count": 1})
    for name in record.get("inactive_parameters", ()):
        rows.append({"address": source_op_id, "what": f"inactive_parameter:{name}", "count": 1})
    if not rows:
        limits.append("residue: the record declares neither losses nor inactive parameters")
    # The setback of an ACCEPTED decision is also something not carried over,
    # and it has its own address: not the source, but the wall for whose sake
    # the author agreed to the trim. The rows live exactly as long as the
    # decision lives, so from one change to the next their count neither
    # grows nor shrinks silently.
    for row in (_thaw(decisions) or ()):
        conceded = float(row.get("conceded_mm", 0.0))
        if conceded <= 0.0:
            continue
        rows.append({"address": str(row["address"]), "what": f"decision:{row['choice']}",
                     "count": 1, "mm": conceded})
    return tuple(rows)


def _decisions_of(project, record):
    """The author's decisions are TYPES and explicit references, not just anything.

    The digest is taken from the PAYLOADS of the decisions, not from their
    addresses: the address must survive regardless, whereas the type's
    content is exactly what a recompute can silently overwrite.
    """
    instances = {item.key: item for item in project.instances}
    rows = []
    for member in record["members"]:
        if "instance_key" not in member:
            continue
        owner = instances.get(member["instance_key"])
        output = next((x for x in owner.outputs if x.key == member["output_key"]),
                      None) if owner else None
        if output is not None:
            rows.append([output_id(project.project_id, member["instance_key"], member["output_key"]),
                         _canonical(output.to_dict())])
    return sorted(rows), _hash([row for row in sorted(rows)])


def refine_after_source_change(store, revision, *, source_output_id: str,
                               change: Mapping[str, Any]) -> RefinementReport:
    """A SOURCE edit after refinement -> what was recomputed, what was preserved, where a decision is needed.

    Writes nothing. The three returned sets are DISJOINT, and their sum
    equals all outputs of the refined instance — otherwise an output could
    disappear silently.

    * `recomputed` — the operation's payload CHANGED under the source's new shape;
    * `preserved` — the payload is the same AND the author's decision (type, explicit reference) is intact;
    * `needs_decision` — the edit touches a wall's AXIS: what the wall
      becomes does not follow from the geometry, and there is nothing to
      choose on the human's behalf here. A question is raised with an
      address, options, and reasoning.
    """
    project = revision if type(revision) is ProjectRevision else None
    if project is None:
        project = store.get(revision) if isinstance(revision, str) else store.head()
    _project(project)
    _require(isinstance(change, Mapping), "invalid_change", "change must be a mapping")
    instance, record = _section_instance(project, source_output_id)
    limits = []

    from kir.project_selection import selected_instance_program

    program = selected_instance_program(project, instance.key)
    before_ops = [_thaw(op) for op in program["ops"]]
    after_ops = _changed_ops(before_ops, change)
    by_id = {op["id"]: op for op in before_ops}
    after_by_id = {op["id"]: op for op in after_ops}
    _require(set(by_id) == set(after_by_id), "invalid_change",
             "a source change may not add or remove section operations")

    touched = _walls_touched(before_ops, change)
    if touched is None:
        touched = []
        limits.append("wall axes not tested: shapely is unavailable")
    # 🔴 A TORN LINK IS A QUESTION, NOT "PRESERVED." A wall whose end lay on
    # the axis of the moved facade not as a corner but as a T-junction is not
    # linked to it by the language: stretching it to follow the facade or
    # leaving it shorter is the author's decision.
    hanging = (_facade_connectivity(before_ops, _change_side(change))[2]
               if change.get("kind") == "facade_curve" else ())
    reasons = {oid: "atrium" for oid in touched}
    for oid in hanging:
        reasons.setdefault(oid, "facade")
    # 🔴 A SLAB THAT DRIFTED OUT FROM UNDER A WALL IS A QUESTION, NOT
    # "RECOMPUTED." What is counted is the DIFFERENCE: edges left without a
    # wall SPECIFICALLY AFTER the edit. An edge that had no wall before the
    # edit either is a property of the scene, not a consequence of the edit,
    # and charging it to the edit would mean reporting on something not its
    # own.
    # NUMBERS are compared per floor, not the edges themselves: an edge that
    # had no wall and simply moved along with the slab is the same edge, and
    # it cannot be charged to the edit. What counts as new is a GROWTH in the
    # number of bare edges on a floor.
    before_bare, after_bare = {}, {}
    for floor_id, _start, _end in _slab_edges_without_walls(before_ops):
        before_bare[floor_id] = before_bare.get(floor_id, 0) + 1
    for floor_id, _start, _end in _slab_edges_without_walls(after_ops):
        after_bare[floor_id] = after_bare.get(floor_id, 0) + 1
    for floor_id, count in after_bare.items():
        if count > before_bare.get(floor_id, 0):
            reasons.setdefault(floor_id, "slab")

    # Decisions whose wall moved away or disappeared: the contract no longer
    # holds, and staying silent about it is not an option either way.
    _stored = _thaw(instance.metadata.get(_DECISIONS_KEY)) if instance.metadata else None
    gone, broken = _stale_decisions(after_ops, _stored)
    for oid in broken:
        reasons.setdefault(oid, "atrium")
    if gone:
        limits.append("a decision addresses a wall that is gone: "
                      f"{len(gone)} ({', '.join(str(x)[:12] for x in gone)})")

    recomputed, preserved, decision = [], [], []
    for oid in sorted(by_id):
        if oid in reasons:
            decision.append(oid)
        elif _canonical(by_id[oid]) != _canonical(after_by_id[oid]):
            recomputed.append(oid)
        else:
            preserved.append(oid)

    # Connectivity is checked by a NUMBER, not by intent: how many ends were
    # left unpaired at their level before the edit and after. A growth in
    # that number must be named — a silent tear in the contour is precisely
    # the owner's finding.
    before_free, after_free = _free_ends(before_ops), _free_ends(after_ops)
    before_loops, after_loops = _closed_loops(before_ops), _closed_loops(after_ops)
    connectivity = {"loose_ends": len(after_free), "closed_loops": after_loops}
    if len(after_free) > len(before_free):
        limits.append(f"wall connectivity: loose ends {len(before_free)} -> {len(after_free)}")
    bare_now = sum(max(0, count - before_bare.get(floor_id, 0))
                   for floor_id, count in after_bare.items())
    if bare_now:
        limits.append(f"slab edges left without a wall: {bare_now}")
    left_behind = _hosted_parts_left_behind(before_ops, change)
    if left_behind:
        limits.append("hosted parts do not follow their host: "
                      f"{len(left_behind)} ({', '.join(str(x)[:12] for x in left_behind)})")
    if after_loops is None:
        limits.append("closed loops not counted: shapely is unavailable")
    elif before_loops is not None and after_loops < before_loops:
        limits.append(f"wall connectivity: closed loops {before_loops} -> {after_loops}")

    # The three sets must cover ALL of the instance's outputs — including
    # those that live in a foreign instance (types). The program already
    # carries them: `selected_instance_program` takes the declared
    # dependency closure.
    total = len(recomputed) + len(preserved) + len(decision)
    _require(total == len(by_id), "set_partition_broken",
             f"three sets cover {total} of {len(by_id)} outputs")

    deviation, dev_limits = _deviation_of(before_ops, after_ops)
    limits.extend(dev_limits)
    reference = record["source"]
    source_op = output_id(reference["project_id"],
                          reference.get(_LIVE_ADDRESS, reference["instance_key"]),
                          reference["output_key"])
    # There is no base yet — so the current state IS R0, and the sum equals
    # the step. This is not an assumption: no edit has been applied from here
    # yet.
    baseline, _fresh = _baseline_row(project, instance, before_ops, source_op)
    deviation = {**deviation, "total": _total_of(baseline, after_ops, source_op)}
    residue = _residue_of(record, source_op, limits,
                          _thaw(instance.metadata.get(_DECISIONS_KEY))
                          if instance.metadata else None)
    _decision_rows, digest = _decisions_of(project, record)

    lineage = {}
    for member in record["members"]:
        owner = member.get("instance_key", instance.key)
        lineage.setdefault(member.get("part_id", reference["output_key"]), []).append(
            output_id(project.project_id, owner, member["output_key"]))

    # A question must name WHAT IS MISSING, and the action. Otherwise the
    # author answers a question whose answer there is nothing here to carry
    # out.
    ungapped = _walls_without_declared_gap(before_ops, decision)
    if ungapped:
        limits.append(f"{_GAP_CODE}: {len(ungapped)} "
                      f"({', '.join(str(x)[:12] for x in ungapped)})")
    questions = tuple(
        Question(question_id=_hash([project.revision_id, oid, change.get("kind")])[:16],
                 address=oid, choices=_CHOICES[reasons[oid]],
                 why=(f"{_WHY[reasons[oid]]}; {_GAP_CODE}: {_GAP_ACTION}"
                      if oid in ungapped else _WHY[reasons[oid]]))
        for oid in decision)

    return RefinementReport(
        revision_before=project.revision_id, source_output_id=str(source_output_id),
        recomputed=tuple(recomputed), preserved=tuple(preserved),
        needs_decision=tuple(decision), residue=residue, deviation=deviation,
        lineage={key: sorted(value) for key, value in sorted(lineage.items())},
        decisions_digest=digest, questions=questions, analysis_limits=tuple(limits),
        connectivity=connectivity)


def apply_source_change(store, revision=None, *, source_output_id: str,
                        change: Mapping[str, Any]) -> str:
    """Apply a source edit and SAVE the recomputed outputs. The report is not the result.

    🔴 A REPORT WITHOUT A WRITE IS A PROMISE, NOT A CHANGE.
    `refine_after_source_change` deliberately writes nothing (it answers
    "what would happen"), and before this move the ONLY way to save anything
    was to answer a question. Owner's measurement, 07.09.2026: after edit B
    the store's head did not move, meaning another process still saw the
    PREVIOUS section, while the report said `recomputed 6`.

    An edit that touches an author's decision is NOT applied from here:
    `needs_decision` is non-empty — a refusal by name, and there is one path:
    `record_pending_change` -> a question -> `answer_question`. Quietly
    applying what was about to be asked about would mean answering on the
    human's behalf.
    """
    from kir.project_merge import ChangeProposal, ProposalScope, accept_proposal
    from kir.project_selection import selected_instance_program

    project = revision if type(revision) is ProjectRevision else (
        store.get(revision) if isinstance(revision, str) else store.head())
    _project(project)
    report = refine_after_source_change(store, project, source_output_id=source_output_id,
                                        change=change)
    _require(not report.needs_decision, "decision_required",
             f"{len(report.needs_decision)} выходов ждут решения автора: "
             f"{[str(oid)[:12] for oid in report.needs_decision]}")
    instance, _record = _section_instance(project, source_output_id)
    program = selected_instance_program(project, instance.key)
    after = {op["id"]: op for op in _changed_ops([_thaw(op) for op in program["ops"]], change)}
    outputs, changed = [], []
    for output in instance.outputs:
        oid = output_id(project.project_id, instance.key, output.key)
        op = after.get(oid)
        if op is None or _canonical({key: value for key, value in op.items() if key != "id"}) == \
                _canonical(_thaw(output.operation)):
            outputs.append(output)
            continue
        outputs.append(replace(output, operation={key: value for key, value in _thaw(op).items()
                                                  if key != "id"}))
        changed.append(oid)
    _require(sorted(changed) == sorted(report.recomputed), "recomputed_set_differs",
             f"пересчитано {len(changed)}, отчёт обещал {len(report.recomputed)}")
    baseline, fresh = _baseline_row(project, instance, program["ops"], source_output_id)
    metadata = _thaw(instance.metadata) if instance.metadata else {}
    updated = replace(instance, outputs=tuple(outputs),
                      metadata={**metadata, _BASELINE_KEY: baseline} if fresh else metadata)
    candidate = project.replace_instance(updated, expected_revision=project.revision_id)
    proposal = ChangeProposal(project, candidate, ProposalScope(instances=(instance.key,)),
                              "kir.project_refinement",
                              f"source change {change.get('kind')} applied")
    accept_proposal(store, proposal, expected_revision=project.revision_id,
                    authorized_scope=ProposalScope(instances=(instance.key,)))
    return store.head().revision_id


_PENDING_KEY = "pending_source_change"
#: 🔴 A DECISION LIVED AS A TAIL OF THE PENDING EDIT AND DIED ALONG WITH IT.
#: The `answered` list sat INSIDE `pending_source_change`, and that was
#: removed entirely once the last question closed. After that, neither a
#: second source change nor another process could name what the author
#: decided or at what address: measurement 07.09.2026 — `answered_decisions`
#: is empty immediately after the answer. The key is separate precisely
#: because a decision has a different lifetime: a pending edit lives until
#: it is answered, a decision lives until the project ends.
_DECISIONS_KEY = "refinement_decisions"


def record_pending_change(store, revision, *, source_output_id: str,
                          change: Mapping[str, Any]) -> str:
    """Record a SOURCE EDIT as an open question, without recomputing anything.

    🔴 WHY A SEPARATE MOVE. `refine_after_source_change` writes NOTHING — it
    answers the question "what would happen." But for the question to survive
    to reach the human and another process, it must live somewhere. No new
    schema is introduced for this: the edit is placed in the same instance's
    metadata, next to the lineage record, and is removed by the answer. While
    it sits there, nothing is recomputed and nothing is lost — this is
    exactly what acceptance checks.
    """
    project = revision if type(revision) is ProjectRevision else store.head()
    instance, _record = _section_instance(project, source_output_id)
    report = refine_after_source_change(store, project,
                                        source_output_id=source_output_id, change=change)
    pending = {"source_output_id": str(source_output_id), "change": _thaw(dict(change)),
               "questions": [question.to_dict() for question in report.questions]}
    from kir.project_selection import selected_instance_program

    baseline, fresh = _baseline_row(project, instance,
                                    selected_instance_program(project, instance.key)["ops"],
                                    source_output_id)
    metadata = {**_thaw(instance.metadata), _PENDING_KEY: pending}
    if fresh:
        metadata[_BASELINE_KEY] = baseline
    updated = replace(instance, metadata=metadata)
    candidate = project.replace_instance(updated, expected_revision=project.revision_id)
    store.commit(candidate, expected_revision=project.revision_id)
    return candidate.revision_id


def _decision_rows_after(existing, *, question_id, choice, address, pending,
                         requested, applied):
    """Decision rows after the answer. One question, one row; repeating does not multiply it."""
    rows = [dict(row) for row in (_thaw(existing) or ())
            if str(row.get("question_id")) != str(question_id)]
    rows.append({"question_id": str(question_id), "choice": str(choice),
                 "address": str(address),
                 "source_output_id": str(pending["source_output_id"]),
                 "change_kind": str(_thaw(pending["change"]).get("kind")),
                 "requested_mm": [list(requested[0]), list(requested[1])],
                 "applied_mm": [list(applied[0]), list(applied[1])],
                 "conceded_mm": float(requested[1][1]) - float(applied[1][1])})
    return sorted(rows, key=lambda row: row["question_id"])


def answered_decisions(store, revision=None) -> tuple:
    """Decisions ALREADY made by the human: address, choice, what was requested and what was given.

    Empty means no decisions were made. Before, empty also meant "the last
    question just closed," and there was no way to tell the two apart.
    """
    project = revision if type(revision) is ProjectRevision else (
        store.get(revision) if isinstance(revision, str) else store.head())
    _project(project)
    rows = []
    for instance in project.instances:
        stored = _thaw(instance.metadata.get(_DECISIONS_KEY)) if instance.metadata else None
        for row in (stored or ()):
            rows.append(dict(row))
    return tuple(sorted(rows, key=lambda row: row["question_id"]))


def open_questions(store, revision=None) -> list:
    """Open questions for the human. Empty means the edit was never filed, not "everything is decided."""
    project = revision if type(revision) is ProjectRevision else (
        store.get(revision) if isinstance(revision, str) else store.head())
    _project(project)
    out = []
    for instance in project.instances:
        pending = _thaw(instance.metadata.get(_PENDING_KEY)) if instance.metadata else None
        if not isinstance(pending, dict):
            continue
        for row in pending.get("questions", ()):
            out.append(Question(question_id=row["question_id"], address=row["address"],
                                choices=tuple(row["choices"]), why=row["why"]))
    return sorted(out, key=lambda question: question.question_id)


def answer_question(store, question_id: str, choice: str) -> str:
    """The human's answer -> the existing `ChangeProposal` -> the existing `accept_proposal`.

    There is no history write of its own here, and no merge of its own
    either: both the proposal and the acceptance are already built. The
    choice MUST come from the declared options — free text cannot be
    accepted here, or a "decision" would stop being a decision from a list
    and become anything at all.
    """
    from kir.project_merge import ChangeProposal, ProposalScope, accept_proposal

    project = store.head()
    for instance in project.instances:
        pending = _thaw(instance.metadata.get(_PENDING_KEY)) if instance.metadata else None
        if not isinstance(pending, dict):
            continue
        row = next((q for q in pending.get("questions", ())
                    if q["question_id"] == question_id), None)
        if row is None:
            continue
        _require(choice in row["choices"], "unknown_choice",
                 f"{choice!r}: not one of the declared choices {tuple(row['choices'])}")
        _require(choice == "keep_wall_and_shrink_atrium", "choice_not_implemented",
                 f"{choice!r}: этот контракт умеет только `keep_wall_and_shrink_atrium`; "
                 "перенос или разрезание стены — отдельная операция, и делать вид, что "
                 "она здесь есть, значило бы отчитаться о непроделанном")
        change = _thaw(pending["change"])
        # The "clearance unprovable" refusal is placed ONCE — where the
        # number is needed (`_shrunk_atrium`), and against the LIVE program,
        # not a recorded row: the question could have been filed BEFORE the
        # author declared the type. A second, identical check used to stand
        # here and was removed: mutation measurement showed the two copies
        # mask each other — remove either one and no probe goes red, meaning
        # neither one guards anything on its own.
        outputs, requested, applied = _shrunk_atrium(instance, change, row["address"], project)
        # 🔴 AN ANSWER BEING APPLIED IS NOT YET "NO MORE QUESTIONS." The
        # previous edition removed the ENTIRE list of pending questions
        # without asking the result what became of it. Owner's measurement,
        # 07.09.2026, scenario C: `keep_wall_and_shrink_atrium` leaves a
        # touch on ALL THREE affected walls, yet 0 questions remained after
        # the answer. Here, after applying, the contour is recomputed and
        # only the questions whose address the new contour no longer touches
        # are closed.
        remaining, recheck_limit = _still_open(project, instance, outputs, pending, row)
        metadata = {key: value for key, value in _thaw(instance.metadata).items()
                    if key != _PENDING_KEY}
        # 🔴 A DECISION'S SETBACK IS A NUMBER WITH AN ADDRESS, NOT A SIDE
        # EFFECT. The author asked for the atrium up to `requested`, got
        # `applied`: the difference is exactly what refinement did NOT carry
        # over. Before, no one carried it, and after the second and third
        # change the remainder stayed the same old constant.
        metadata[_DECISIONS_KEY] = _decision_rows_after(
            metadata.get(_DECISIONS_KEY), question_id=question_id, choice=choice,
            address=row["address"], pending=pending, requested=requested, applied=applied)
        if remaining:
            metadata[_PENDING_KEY] = {**_thaw(pending), "questions": remaining,
                                      "answered": [*(_thaw(pending).get("answered") or ()),
                                                   {"question_id": question_id, "choice": choice}],
                                      **({"recheck_limit": recheck_limit} if recheck_limit else {})}
        updated = replace(instance, outputs=outputs, metadata=metadata)
        candidate = project.replace_instance(updated, expected_revision=project.revision_id)
        proposal = ChangeProposal(project, candidate, ProposalScope(instances=(instance.key,)),
                                  "kir.project_refinement", f"answer:{question_id}:{choice}")
        accept_proposal(store, proposal, expected_revision=project.revision_id,
                        authorized_scope=ProposalScope(instances=(instance.key,)))
        return store.head().revision_id
    raise RefinementError("unknown_question", f"{question_id}: no such open question")


def _wall_half_width(wall, program) -> float | None:
    """A wall's half-width comes from the DECLARED type, not from an assumption."""
    reference = wall.get("type")
    if not isinstance(reference, Mapping) or reference.get("by") != "ref":
        return None
    target = str(reference.get("value"))
    for op in program["ops"]:
        if op.get("id") != target or op.get("op") != "create_wall_type":
            continue
        widths = [float(layer.get("width_mm", 0.0)) for layer in (op.get("layers") or ())]
        return sum(widths) / 2.0 if widths else None
    return None


def _still_open(project, instance, outputs, pending, answered_row):
    """Which questions REMAIN open after applying the answer — against the NEW contour.

    Straight rings are checked against the real CONTOUR edges at the wall's
    level. An arc's bounding box can only prove the absence of contact; when
    the bounding boxes intersect, the question stays open with its reason,
    rather than being judged by a chord approximation. Unresolved geometry
    also does not close a question.
    """
    from kir.contour import edges_are_straight, edges_bbox, edges_vertices, is_spline

    try:
        from shapely.geometry import LineString, Polygon, box as rectangle
    except ImportError:
        reason = "recheck not done: shapely is unavailable"
        return [{**dict(row), "why": reason} for row in pending.get("questions", ())], reason

    walls = {output_id(project.project_id, instance.key, output.key): _thaw(output.operation)
             for output in outputs if output.operation.get("op") == "create_wall"}
    floors = [_thaw(output.operation) for output in outputs
              if output.operation.get("op") == "create_floor_by_contour"]
    remaining, limits = [], set()
    for row in pending.get("questions", ()):
        wall = walls.get(row["address"])
        reason, touched = None, False
        own_floors = [floor for floor in floors if wall and _level_key(floor) == _level_key(wall)]
        if not wall or not own_floors:
            reason = "recheck not done: question has no wall/floor association on its level"
        else:
            try:
                axis = LineString([wall["p0_mm"], wall["p1_mm"]])
                for floor in own_floors:
                    for hole in floor["contour"].get("holes") or ():
                        edges = _hole_edges(hole)
                        if any(is_spline(edge[2]) for edge in edges):
                            reason = "recheck not done: exact spline bounds are unavailable"
                        elif not rectangle(*edges_bbox(edges)).intersects(axis):
                            continue
                        elif not edges_are_straight(edges):
                            reason = "recheck not done: curved hole/axis intersection is unavailable"
                        elif Polygon(edges_vertices(edges)).intersects(axis):
                            touched = True
            except Exception as exc:
                reason = f"recheck not done: hole/axis geometry unavailable ({type(exc).__name__})"
        if not touched and reason is None:
            continue
        if reason:
            limits.add(reason)
        why = (reason if reason else
               f"{row['why']}; ответ `{answered_row['question_id'][:8]}` применён, но новый "
               f"контур по-прежнему задевает эту ось")
        remaining.append({**dict(row), "why": why})
    return remaining, "; ".join(sorted(limits)) or None


def _shrunk_atrium(instance, change, address, project):
    """The hole is trimmed so as NOT to reach the affected axis. The numbers are the declared ones."""
    from kir.project_selection import selected_instance_program

    program = selected_instance_program(project, instance.key)
    wall = next((op for op in program["ops"] if op["id"] == address), None)
    _require(wall is not None, "unknown_question", "the question addresses no section wall")
    hole = _rect(change.get("hole_mm"), "change.hole_mm")
    ys = [float(wall["p0_mm"][1]), float(wall["p1_mm"][1])]
    limit = min(y for y in ys if y > hole[0][1]) if any(y > hole[0][1] for y in ys) else hole[1][1]
    # 🔴 TRIMMING TO THE AXIS MEANS LEAVING A TOUCH, THAT IS, NOT RESOLVING
    # THE QUESTION. The answer is named "keep the wall and trim the atrium";
    # a wall whose axis the hole touches exactly is left cut in half — and a
    # repeated check honestly leaves the question open. The half-width is not
    # taken out of thin air: it is DECLARED by the wall type
    # (`create_wall_type.layers`) the wall references. If the type or the
    # width is not declared, the trim goes to the axis as before — and the
    # question stays open WITH A REASON, rather than being closed.
    half = _wall_half_width(wall, program)
    _require(half is not None, _GAP_CODE, f"{str(address)[:12]}: {_GAP_ACTION}")
    limit -= half
    shrunk = (hole[0], (hole[1][0], min(hole[1][1], limit)))
    outputs = []
    for output in instance.outputs:
        if output.operation["op"] != "create_floor_by_contour":
            outputs.append(output)
            continue
        contour = _replace_atrium_hole(output.operation["contour"], hole, shrunk)
        outputs.append(replace(output, operation={**_thaw(output.operation), "contour": contour}))
    return outputs, hole, shrunk
