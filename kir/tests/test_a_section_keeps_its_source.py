# -*- coding: utf-8 -*-
"""A section is a DERIVATIVE of the concept, not its replacement (stage A2,
07.09.2026).

The stage's measure is named by a reconnaissance number: an edit to the
source form AFTER detailing was not reaching the descendants (`changed 0 ·
affected 1 · unchanged 23`), because the concept vanished from the head while
`refinement.source` pointed into the past. What is checked here is exactly
this, and exactly by the number.
"""
from __future__ import annotations

from collections import deque

import pytest

from examples import residential_project as towers
from examples import residential_refinement as workflow
from examples import residential_typed_section as typed
from kir.project import ModuleInstance, _thaw, output_id
from kir.project_diff import _dependencies, _outputs, _refinement_edges, diff_projects
from kir.project_refinement import (REFINEMENT_SCHEMA, REFINEMENT_SCHEMA_V2, RefinementError,
                                    annotate_schematic_refinement, refinement_view)
from kir.project_selection import selected_instance_program
from kir.tests.fixtures import GROUND_SNAPSHOT as G

INSTANCE = "tower-a"


@pytest.fixture(scope="module")
def scene():
    """The same scene as the acceptance instrument: concept -> section -> types."""
    source = towers.concept()
    base = workflow.develop_section(source, height_mm=4200., setback_mm=1800.)
    detailed = typed.add_section_types(
        base, source=source, expected_revision=base.revision_id,
        wall_name="KIR_Section_Wall_230",
        wall_layers=[{"width_mm": 15, "function": "Finish1"},
                     {"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                     {"width_mm": 15, "function": "Finish2"}],
        wall_source_type={"by": "element_id", "value": G["wall_types"][0]["id"]},
        floor_name="KIR_Section_Floor_260",
        floor_layers=[{"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                      {"width_mm": 50, "function": "Substrate"},
                      {"width_mm": 10, "function": "Finish1"}],
        floor_source_type={"by": "element_id", "value": G["floor_types"][0]["id"]})
    return source, detailed


def test_the_concept_survives_its_own_detailing(scene):
    """RED of the reconnaissance: 0 occurrences of the concept op in the head. Here there must be 1."""
    source, detailed = scene
    blends = [(instance.key, output.key) for instance in detailed.instances
              for output in instance.outputs if output.operation["op"] == "create_solid_blend"]
    assert (workflow.CONCEPT_SUFFIX and
            (INSTANCE + workflow.CONCEPT_SUFFIX, "concept-volume") in blends), blends
    view = refinement_view(detailed, INSTANCE, source=source)
    assert view["live_source"]["present"] is True
    assert view["live_source"]["instance_key"] == INSTANCE + workflow.CONCEPT_SUFFIX
    # A live address is not a promise: the payload at it must match the pinned one.
    assert view["live_source"]["payload"] == "identical_to_pinned_digest"
    # The historical pin is NOT weakened: it is in place and points to the same revision.
    assert view["source"]["revision_id"] == source.revision_id


def test_every_output_of_the_section_has_an_address(scene):
    """The acceptance instrument's measure, item (a): 0 non-addressable out of 23."""
    source, detailed = scene
    program = selected_instance_program(detailed, INSTANCE)
    view = refinement_view(detailed, INSTANCE, source=source)
    assert len(program["ops"]) == 23
    assert len(view["members"]) == 23
    addressed = {member["op_id"] for member in view["members"]}
    assert {op["id"] for op in program["ops"]} == addressed, "неадресуемых обязано быть 0"
    # Two of them live as A FOREIGN instance — and this is named, not hidden.
    foreign = [m for m in view["members"] if "instance_key" in m]
    assert len(foreign) == 2 and {m["role"] for m in foreign} == {"wall_type"}


def test_two_different_source_parts_never_share_a_child(scene):
    """The source's parts are A PARTITION. Otherwise "which part gave rise to this wall" has no answer."""
    source, detailed = scene
    view = refinement_view(detailed, INSTANCE, source=source)
    lineage = view["lineage"]
    assert len(lineage) >= 2
    seen = {}
    for part, children in lineage.items():
        for child in children:
            assert child not in seen, f"{child}: назван двумя частями ({seen.get(child)}, {part})"
            seen[child] = part
    assert len(seen) == len(view["members"]), "часть обязана быть у каждого потомка"
    assert set(lineage["atrium"]) & set(lineage["north_facade"]) == set()
    assert len(lineage["atrium"]) == 3 and len(lineage["north_facade"]) == 3


def _reachable(project, view, edges):
    down = {}
    for edge in edges:
        down.setdefault(edge["source"], set()).add(edge["dependent"])
    seen, queue = set(), deque([view["live_source"]["op_id"]])
    while queue:
        for nxt in down.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def test_the_source_edge_is_what_connects_the_concept_to_its_children(scene):
    """RED -> GREEN of reachability: 0 -> 23. The control removes EXACTLY this edge."""
    source, detailed = scene
    view = refinement_view(detailed, INSTANCE, source=source)
    members = {member["op_id"] for member in view["members"]}
    operations, _ = _outputs(detailed)
    planner, _issues = _dependencies(detailed, operations)
    mine = _refinement_edges(detailed)
    # The planner does not know about lineage and cannot know: the concept
    # volume is not in the section's program, this is not a reference but
    # the author's assertion.
    assert sum(1 for e in planner if e["source"] == view["live_source"]["op_id"]) == 0
    assert len(_reachable(detailed, view, planner) & members) == 0
    assert len(_reachable(detailed, view, planner + mine) & members) == len(members) == 23


def test_moving_the_atrium_after_detailing_marks_its_three_floors(scene):
    """Stage acceptance: an edit to the source form must reach the descendants."""
    source, detailed = scene
    view = refinement_view(detailed, INSTANCE, source=source)
    part_of = {member["op_id"]: member.get("part_id") for member in view["members"]}
    concept = next(item for item in detailed.instances
                   if item.key == view["live_source"]["instance_key"])
    parameters = dict(_thaw(concept.parameters))
    parameters["atrium_radius_mm"] = 3000.
    moved = ModuleInstance(concept.key, concept.module_key, list(concept.outputs), parameters,
                           metadata=_thaw(concept.metadata))
    after = detailed.revise(expected_revision=detailed.revision_id,
                            instances=[moved if item.key == concept.key else item
                                       for item in detailed.instances])
    report = diff_projects(detailed, after).to_dict()
    marked = set(report["affected"]) & set(part_of)
    assert marked == set(part_of), "ни один потомок не вправе промолчать"
    floors = [oid for oid in marked if part_of[oid] == "atrium"]
    assert len(floors) == 3
    rows = {row["op_id"]: row for row in report["outputs"]}
    for oid in floors:
        assert rows[oid]["payload_status"] == "unchanged" and rows[oid]["impact"] == "reconsider"
        assert "dependency_changed" in rows[oid]["reasons"]


def test_an_opening_qualifies_and_a_facade_grid_is_refused_by_name():
    """Roles: the opening takes its category FROM THE OP; the facade grid refuses BY NAME."""
    from kir import spec
    from kir.project_refinement import _REFUSED_ROLES, _ROLES

    assert set(_ROLES) >= {"opening", "window", "door", "roof", "wall_type"}
    # An opening's category is not a constant: the registry declares THREE,
    # and which one comes out is decided by the host. That's why the table
    # holds None, not a made-up single value.
    assert _ROLES["opening"][2] is None
    assert len(spec.op_result_categories({"op": "create_opening"})) == 3
    assert set(_REFUSED_ROLES) >= {"curtain_grid", "curtain_panel"}
    # The refusal is not made up: these ops genuinely have nothing to address.
    assert spec.OPS["create_curtain_grid_line"].result.reference_kind is None
    assert spec.OPS["set_curtain_panel"].effect.name == "MUTATE"


def test_a_record_without_parts_still_reads(scene):
    """A read migration: `/1` requires neither an edit on disk nor new fields."""
    source, _detailed = scene
    base = towers.develop_section(source, height_mm=4200., setback_mm=1800.)
    replacement = next(item for item in base.instances if item.key == INSTANCE)
    from dataclasses import replace as _replace

    bare = _replace(replacement, metadata={key: value
                                           for key, value in _thaw(replacement.metadata).items()
                                           if key not in ("refines", "refinement")})
    annotated = annotate_schematic_refinement(
        source, bare, source_instance_key=INSTANCE, source_output_key="concept-volume",
        roles={output.key: {"create_level": "level", "create_floor_by_contour": "slab",
                            "create_wall": "wall", "create_room": "space"}[output.operation["op"]]
               for output in bare.outputs},
        losses=("concept_twist_removed",))
    record = _thaw(annotated.metadata["refinement"])
    assert record["schema"] == REFINEMENT_SCHEMA, "без частей и живого адреса запись остаётся /1"
    assert "live_instance_key" not in record["source"]
    older = base.replace_instance(annotated, expected_revision=base.revision_id)
    view = refinement_view(older, INSTANCE, source=source)
    assert view["live_source"]["present"] is False
    assert list(view["lineage"]) == ["concept-volume"], "источник один — и это сказано вслух"
    assert len(view["members"]) == 21


def test_half_marked_parts_are_refused(scene):
    """A half-done part partitioning would leave descendants without an address — refused by name."""
    source, detailed = scene
    instance = next(item for item in detailed.instances if item.key == INSTANCE)
    record = _thaw(instance.metadata["refinement"])
    assert record["schema"] == REFINEMENT_SCHEMA_V2
    broken = {**record, "members": [{k: v for k, v in member.items() if k != "part_id"}
                                    if index == 0 else member
                                    for index, member in enumerate(record["members"])]}
    from dataclasses import replace as _replace

    bad = _replace(instance, metadata={**_thaw(instance.metadata), "refinement": broken})
    hurt = detailed.replace_instance(bad, expected_revision=detailed.revision_id)
    with pytest.raises(RefinementError, match="part_id must be declared"):
        refinement_view(hurt, INSTANCE, source=source)
