"""A project's own ungrounded selector must not block two unrelated passports.

The subject is `kir.project_merge.merge_proposal`. A project that legitimately
carries a backend seed selector (`source_type={"by": "element_id", …}`) has an
INCOMPLETE explicit-reference analysis: that selector is grounded in Revit, not
in the authoring graph. Until 13.09.2026 that incompleteness refused EVERY
divergent merge in the project — including two renames of two different
instances, where not a single operation changed on either side. Measured on the
saved complex of `examples/final_result_walkthrough.py` (9 instances, 2 such
selectors): `dependency_analysis_incomplete`, then `dependency_overlap`, with
`dependency_issues` byte-identical before and after on both sides.

The controls below are the point of the file: a side that touched an OPERATION,
or that CHANGED the gap itself, is still refused. Nothing here is allowed to
turn into "all merges are clean now".
"""
from dataclasses import replace

from kir import sdk
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id
from kir.project_diff import diff_projects
from kir.project_merge import ChangeProposal, ProposalScope, merge_proposal

PROJECT = "gap-and-passports"

#: The backend seed: a REAL, legitimate reason for an incomplete analysis. The
#: value is grounded by the connector, never by the authoring graph.
SEED = {"by": "element_id", "value": 42}


def _types(seeds):
    return {f"type-{index}": {"op": "create_wall_type", "host_kind": "wall",
                              "new_name": f"Стена {index}",
                              "layers": [{"material": "Бетон", "thickness_mm": 200.0}],
                              "source_type": seed}
            for index, seed in enumerate(seeds, start=1)}


def base_project(*, seeds=(SEED,)):
    """`types`: the ungroundable seed · `a`: a level · `b`: a wall on a/level."""
    wall = sdk.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000,
                           level=sdk.ref(output_id(PROJECT, "a", "level")))
    return ProjectRevision(PROJECT, [ModuleDefinition("explicit")], [
        ModuleInstance("types", "explicit", _types(seeds), metadata={"title": "типы"}),
        ModuleInstance("a", "explicit", {"level": sdk.create_level(elev_mm=0, name="a")},
                       metadata={"title": "Первый этаж"}),
        ModuleInstance("b", "explicit", {"wall": wall}, metadata={"title": "Секция Б"}),
    ], metadata={"units": "mm"})


def instance(project, key):
    return next(item for item in project.instances if item.key == key)


def renamed(project, key, title):
    """A passport-only edit: not one operation changes."""
    target = instance(project, key)
    return project.replace_instance(
        replace(target, metadata={**dict(target.metadata), "title": title}),
        expected_revision=project.revision_id)


def raised(project, key, elevation):
    """A real operation edit."""
    target = instance(project, key)
    return project.replace_instance(
        replace(target, outputs={"level": sdk.create_level(elev_mm=elevation, name=key)}),
        expected_revision=project.revision_id)


def with_second_seed(project):
    """This side CHANGES the gap itself: a second ungroundable selector appears."""
    target = instance(project, "types")
    return project.replace_instance(
        replace(target, outputs=_types((SEED, {"by": "element_id", "value": 43}))),
        expected_revision=project.revision_id)


def merge(base, candidate, *keys, current):
    change = ChangeProposal(base, candidate, ProposalScope(instances=keys),
                            "агент", "проверка ложного конфликта")
    return merge_proposal(change, current, authorized_scope=change.scope)


def kinds(result):
    return sorted(row["kind"] for row in result.to_dict()["conflicts"])


def test_the_gap_is_real_and_is_not_created_by_either_edit():
    """The premise of the whole file: the analysis IS incomplete, and the
    incompleteness is a property of the project, identical before and after."""
    base = base_project()
    delta = diff_projects(base, renamed(base, "a", "Цоколь")).to_dict()
    assert delta["analysis"]["explicit_reference_analysis_complete"] is False
    assert delta["dependency_issues"]["before"] == delta["dependency_issues"]["after"]
    assert [issue["kind"] for issue in delta["dependency_issues"]["before"]] == \
           ["selector_requires_grounding"]
    assert not (delta["added"] or delta["removed"] or delta["changed"] or delta["rekeyed"])


def test_two_passports_of_two_instances_merge_despite_the_gap():
    base = base_project()
    current = renamed(base, "b", "Секция Б (переименована)")
    result = merge(base, renamed(base, "a", "Первый этаж (был цоколь)"), "a", current=current)
    assert result.clean, kinds(result)
    assert result.to_dict()["result_revision"] is not None
    assert result.to_dict()["status"] == "merged"


def test_the_same_pair_merges_in_the_other_direction_too():
    """Symmetry is not decoration: an asymmetric merge would mean the verdict
    depends on who pressed the button first."""
    base = base_project()
    current = renamed(base, "a", "Первый этаж (был цоколь)")
    result = merge(base, renamed(base, "b", "Секция Б (переименована)"), "b", current=current)
    assert result.clean, kinds(result)
    assert result.to_dict()["result_revision"] is not None


def test_control_an_operation_edit_is_still_refused_while_the_gap_stands():
    """THE CONTROL. One side raised a level — an operation changed, and a
    dependency edge the analysis could not resolve may be its own."""
    base = base_project()
    current = renamed(base, "b", "Секция Б (переименована)")
    result = merge(base, raised(base, "a", 3000), "a", current=current)
    assert not result.clean
    assert kinds(result) == ["dependency_analysis_incomplete"]
    assert result.to_dict()["result_revision"] is None


def test_control_the_refusal_does_not_depend_on_which_side_edited_an_operation():
    base = base_project()
    current = raised(base, "a", 3000)
    result = merge(base, renamed(base, "b", "Секция Б (переименована)"), "b", current=current)
    assert not result.clean
    assert kinds(result) == ["dependency_analysis_incomplete"]


def test_control_a_side_that_changes_the_gap_itself_is_refused():
    """THE SECOND CONTROL. The passport lift applies only while the side's
    `dependency_issues` stand unchanged; here a side ADDS an ungroundable
    selector, so the premise is gone and the refusal must come back."""
    base = base_project()
    current = renamed(base, "a", "Первый этаж (был цоколь)")
    result = merge(base, with_second_seed(base), "types", current=current)
    assert not result.clean
    assert "dependency_analysis_incomplete" in kinds(result)


def test_a_real_dependency_overlap_is_still_a_conflict_without_any_gap():
    """The lift is about the GAP, not about overlap: with every selector
    grounded, two edits of the same dependency chain still collide."""
    base = base_project(seeds=())
    delta = diff_projects(base, renamed(base, "a", "Цоколь")).to_dict()
    assert delta["analysis"]["explicit_reference_analysis_complete"] is True
    current = raised(base, "a", 3000)
    # `b`'s wall stands on `a`'s level: both sides move the same chain.
    other = base.replace_instance(
        replace(instance(base, "b"), outputs={"wall": {
            **dict(instance(base, "b").outputs[0].operation), "height_mm": 4000}}),
        expected_revision=base.revision_id)
    result = merge(base, other, "b", current=current)
    assert not result.clean
    assert kinds(result) == ["dependency_overlap"]
