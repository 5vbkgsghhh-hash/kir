"""F2/P04 probes: metadata-only false conflicts and the merge's dependency scope.

The subject is `kir.project_merge.merge_proposal`: where a refusal is
caused by DATA (the same parameter, the same output, a real dependency),
and where it is a metadata edit that touches not a single operation.
"""
from dataclasses import replace

import pytest

from kir import sdk
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id
from kir.project_merge import ChangeProposal, ProposalScope, merge_proposal

PROJECT = "m7"


def base_project():
    """a: a level · b: a wall referencing a/level · z: connected to no one."""
    wall = sdk.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000,
                           level=sdk.ref(output_id(PROJECT, "a", "level")))
    return ProjectRevision(PROJECT, [ModuleDefinition("explicit")], [
        ModuleInstance("a", "explicit", {"level": sdk.create_level(elev_mm=0, name="a")},
                       parameters={"elev_mm": 0, "grade": "B25"},
                       metadata={"title": "Первый этаж"}),
        ModuleInstance("b", "explicit", {"wall": wall}),
        ModuleInstance("z", "explicit", {"level": sdk.create_level(elev_mm=9000, name="z")}),
    ], metadata={"units": "mm"})


def with_instance(project, instance):
    return project.replace_instance(instance, expected_revision=project.revision_id)


def instance(project, key):
    return next(item for item in project.instances if item.key == key)


def rename(project, key, title):
    """An edit to ONLY the instance's metadata: not a single output changes."""
    return with_instance(project, replace(instance(project, key),
                                          metadata={**dict(instance(project, key).metadata), "title": title}))


def raise_level(project, key, elevation):
    return with_instance(project, replace(instance(project, key), outputs={
        "level": sdk.create_level(elev_mm=elevation, name=key)}))


def widen_wall(project, height):
    wall = dict(instance(project, "b").outputs[0].operation)
    return with_instance(project, ModuleInstance("b", "explicit", {"wall": {**wall, "height_mm": height}}))


def merge(base, candidate, *keys, current, fields=()):
    change = ChangeProposal(base, candidate, ProposalScope(instances=keys, project_fields=fields),
                            "agent", "probe")
    return merge_proposal(change, current, authorized_scope=change.scope)


def kinds(result):
    return {row["kind"] for row in result.to_dict()["conflicts"]}


def test_a_metadata_only_edit_does_not_block_an_edit_of_a_dependent_instance():
    """A renamed the level, B raised the wall that references it."""
    base = base_project()
    current = widen_wall(base, 3500)
    result = merge(base, rename(base, "a", "Первый этаж (был цоколь)"), "a", current=current)
    assert result.clean, kinds(result)
    assert instance(result.revision, "a").metadata["title"] == "Первый этаж (был цоколь)"
    assert instance(result.revision, "b").to_dict() == instance(current, "b").to_dict()


def test_dependency_scope_is_exactly_the_dependents_not_the_whole_project():
    """A genuine source edit — a refusal, and the address is exactly one: the dependent output."""
    base = base_project()
    result = merge(base, raise_level(base, "a", 500), "a", current=widen_wall(base, 3500))
    assert kinds(result) == {"dependency_overlap"}
    assert result.to_dict()["conflicts"][0]["op_ids"] == [output_id(PROJECT, "b", "wall")]
    assert output_id(PROJECT, "z", "level") not in result.to_dict()["conflicts"][0]["op_ids"]


def test_a_metadata_edit_that_moves_a_refinement_record_is_not_inert():
    """`metadata['refinement']` is an author-declared dependency edge, not metadata."""
    base = base_project()
    record = {"source": {"instance_key": "a", "output_key": "level"},
              "members": [{"output_key": "wall", "instance_key": "b"}]}
    base = with_instance(base, replace(instance(base, "b"), metadata={"refinement": record}))
    candidate = with_instance(base, replace(instance(base, "b"), metadata={"refinement": {
        **record, "members": [{"output_key": "wall", "instance_key": "b"},
                              {"output_key": "level", "instance_key": "z"}]}}))
    result = merge(base, candidate, "b", current=raise_level(base, "a", 500))
    assert not result.clean, "новое ребро детализации не должно молча слиться"


@pytest.mark.xfail(strict=True, reason=(
    "СТОЛКНОВЕНИЕ КОНТРАКТОВ, не забытая правка: атомарность строки экземпляра "
    "закреплена числом в kir/tests/test_project_merge.py::"
    "test_instance_is_atomic_even_if_two_agents_change_different_internal_fields "
    "(строка 91) и доктриной project_merge.__doc__: параметры/выходы/пин рецепта "
    "не сливаются по полям в результат, которого никто не получал. Мандат F2 просит "
    "обратного. Решение о контракте принимает владелец, а не эта правка."))
def test_a_metadata_only_change_of_one_instance_merges_with_its_parameter_change():
    """Probe (a) of the mandate: metadata X and parameter X from the same base."""
    base = base_project()
    current = with_instance(base, replace(instance(base, "a"),
                                          parameters={"elev_mm": 0, "grade": "B30"}))
    result = merge(base, rename(base, "a", "Отметка ±0.000"), "a", current=current)
    assert result.clean, kinds(result)
    assert instance(result.revision, "a").metadata["title"] == "Отметка ±0.000"
    assert instance(result.revision, "a").parameters["grade"] == "B30"


@pytest.mark.xfail(strict=True, reason=(
    "СТОЛКНОВЕНИЕ КОНТРАКТОВ, не забытая правка: атомарность строки экземпляра "
    "закреплена числом в kir/tests/test_project_merge.py::"
    "test_instance_is_atomic_even_if_two_agents_change_different_internal_fields "
    "(строка 91) и доктриной project_merge.__doc__: параметры/выходы/пин рецепта "
    "не сливаются по полям в результат, которого никто не получал. Мандат F2 просит "
    "обратного. Решение о контракте принимает владелец, а не эта правка."))
def test_two_different_parameters_of_one_instance_merge():
    """Probe (b1) of the mandate: different parameters of one instance."""
    base = base_project()
    current = with_instance(base, replace(instance(base, "a"),
                                          parameters={"elev_mm": 0, "grade": "B30"}))
    candidate = with_instance(base, replace(instance(base, "a"),
                                            parameters={"elev_mm": 150, "grade": "B25"}))
    result = merge(base, candidate, "a", current=current)
    assert result.clean, kinds(result)
    assert dict(instance(result.revision, "a").parameters) == {"elev_mm": 150, "grade": "B30"}


def test_the_same_parameter_with_two_values_is_a_data_conflict_with_an_address():
    """Probe (b2): one parameter, two values — a refusal on the data, not "last one wins"."""
    base = base_project()
    current = with_instance(base, replace(instance(base, "a"),
                                          parameters={"elev_mm": 300, "grade": "B25"}))
    candidate = with_instance(base, replace(instance(base, "a"),
                                            parameters={"elev_mm": 150, "grade": "B25"}))
    result = merge(base, candidate, "a", current=current)
    assert not result.clean and result.revision is None
    row = result.to_dict()["conflicts"][0]
    assert row["kind"] == "modify_modify" and row["path"] == "instances/a"
    assert row["current_sha256"] != row["proposed_sha256"] != row["base_sha256"]


def test_an_unknown_attachment_survives_the_merge_byte_for_byte():
    """Probe (d): a nesting merge does not understand is neither lost nor silently fixed."""
    base = base_project()
    unknown = {"vendor.x/attachment": {"blob": [" ", -0.0, True, 1, {"n": None}],
                                       "schema": "not-known-to-merge/9"}}
    candidate = with_instance(base, replace(instance(base, "z"),
                                            metadata={**dict(instance(base, "z").metadata), **unknown}))
    result = merge(base, candidate, "z", current=widen_wall(base, 3500))
    assert result.clean, kinds(result)
    assert instance(result.revision, "z").to_dict() == instance(candidate, "z").to_dict()
    assert result.revision.to_dict()["metadata"] == base.to_dict()["metadata"]


# --- Counter-probes against my own fix (self-review 07.09) --------------------

#: Metadata keys that the PRODUCT code READS (not tests). Measured by grep:
#: refinement — project_diff.py:247, project_refinement.py:225/278/952;
#: refines — project_refinement.py:252/291/293;
#: recipe_evaluation — project_recipe.py:171-180;
#: ownership_handoff — project_handoff.py:54/78;
#: pending_source_change — project_refinement.py:1206/1239/1260/1285,
#: viewer/standalone_export.py:324.
#: refinement_decisions — project_refinement.py:1282/1198/1334/1396
#: (`_DECISIONS_KEY`, `answered_decisions`), set up by the refine agent on 07.09.
#: category, source_category — kir/clash/repair_profile.py:189 (`classify`), :213-215 (`classify`),
#: set up by the rules agent on 07.09: the category word decides the repair refusal.
#: refinement_baseline — kir/project_refinement.py:1161/1184 (`_BASELINE_KEY`,
#: `_baseline_row`), set up by the refine agent on 07.09: the R0 base of accumulated deviation.
LOAD_BEARING = ("refinement", "refines", "recipe_evaluation",
                "ownership_handoff", "pending_source_change",
                "refinement_decisions", "category", "source_category",
                "refinement_baseline")


@pytest.mark.parametrize("key", LOAD_BEARING)
def test_a_load_bearing_metadata_key_is_never_treated_as_inert(key):
    """An edit to a key the product reads must not merge silently."""
    base = base_project()
    record = {"schema": "probe/1", "source": {"instance_key": "a", "output_key": "level"},
              "members": [{"output_key": "level"}], "questions": ["?"]}
    # The category is a word, not a record: the value is taken by the
    # key's kind, otherwise the probe would measure a shape the product
    # never writes into this slot.
    measure = {"schema": "kir-refinement-baseline/1", "revision_id": base.revision_id,
               "op_count": 3, "volume_mm3": 1.25e9, "plan_area_by_level": {"a": 42.0}}
    value = ("OST_DuctCurves" if key in ("category", "source_category")
             else measure if key == "refinement_baseline" else record)
    candidate = with_instance(base, replace(instance(base, "a"), metadata={
        **dict(instance(base, "a").metadata), key: value}))
    result = merge(base, candidate, "a", current=widen_wall(base, 3500))
    assert not result.clean, f"паспортный ключ {key} читается продуктом, а слился молча"


def test_a_delta_without_reasons_stays_conservative(monkeypatch):
    """A delta without the `reasons` field (a different producer / old data) is not "everything is inert"."""
    import kir.project_merge as merge_module
    from kir.project_diff import ProjectDiff

    real = merge_module.diff_projects

    def stripped(before, after):
        data = real(before, after).to_dict()
        data["outputs"] = [{key: value for key, value in row.items() if key != "reasons"}
                           for row in data["outputs"]]
        return ProjectDiff(data)

    monkeypatch.setattr(merge_module, "diff_projects", stripped)
    base = base_project()
    result = merge(base, rename(base, "a", "Первый этаж (был цоколь)"), "a",
                   current=widen_wall(base, 3500))
    assert not result.clean, "без причин обход обязан остаться консервативным"


@pytest.mark.parametrize("removal", ["delete", "rekey"])
def test_a_metadata_edit_against_a_removed_instance_is_refused_with_an_address(removal):
    """A edits metadata X, B deletes/renames X — a refusal with an address."""
    base = base_project()
    kept = [item for item in base.instances if item.key != "a"]
    if removal == "rekey":
        kept = [replace(instance(base, "a"), key="a2"), *kept]
    current = base.with_instances(tuple(kept), expected_revision=base.revision_id)
    result = merge(base, rename(base, "a", "Отметка ±0.000"), "a", current=current)
    assert not result.clean and result.revision is None
    paths = {row["path"] for row in result.to_dict()["conflicts"]}
    assert "instances/a" in paths, paths


def test_the_closed_list_of_load_bearing_metadata_keys_is_not_stale():
    """An instrument against list rot: it re-reads the product's own sources.

    The blind spot is named: the forms caught are `.metadata.get("k")`,
    `.metadata["k"]`, `"k" in x.metadata`, and the same forms on a local
    copy named `metadata` (this is how `project_recipe.py` reads),
    including a named constant. A read through a variable with a DIFFERENT
    name (`meta = instance.metadata`) is not visible.
    """
    import importlib
    import re
    from pathlib import Path

    from kir.project_merge import _LOAD_BEARING_METADATA

    root = Path(__file__).resolve().parents[1]
    literal = re.compile(r"""\bmetadata(?:\.get\(|\[)\s*(?:"([\w.\-/]+)"|'([\w.\-/]+)')""")
    named = re.compile(r"""\bmetadata(?:\.get\(|\[)\s*(_[A-Z][A-Z0-9_]*)""")
    membership = re.compile(r"""(?:"([\w.\-/]+)"|'([\w.\-/]+)')\s+in\s+[\w.]*\bmetadata\b""")
    # `metadata` here is NOT the instance's metadata, but a federation
    # wrapper record (`record.extra["federation"]`,
    # federated_clash_query.py:113).
    foreign = {"federated_clash_query.py"}
    found = {}
    for path in sorted(root.rglob("*.py")):
        if "tests" in path.parts or path.name.startswith("test_") or path.name in foreign:
            continue
        text = path.read_text(encoding="utf-8")
        module = "kir." + str(path.relative_to(root).with_suffix("")).replace("/", ".")
        module = module.replace(".__init__", "")
        for pattern in (literal, membership):
            for match in pattern.finditer(text):
                found[match.group(1) or match.group(2)] = f"{path.name}"
        for match in named.finditer(text):
            value = getattr(importlib.import_module(module), match.group(1), None)
            if isinstance(value, str):
                found[value] = f"{path.name}:{match.group(1)}"
    # A blindness control: the instrument must see all the declared keys.
    assert set(_LOAD_BEARING_METADATA) <= set(found), sorted(found)
    assert set(found) <= set(_LOAD_BEARING_METADATA), {
        key: place for key, place in found.items() if key not in _LOAD_BEARING_METADATA}
