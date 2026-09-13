# -*- coding: utf-8 -*-
"""THE SECOND ANALYSIS IS PAID FOR ONCE — AND SAYS EXACTLY THE SAME
THING.

🔴 THE NUMBER THAT OPENED THIS FILE (07.09.2026, N=2000).
`reanalyze_after_fix` is the same `analyze_project`, and it was calling
`GeometryBundle.rederive_preview()` on EVERY body on EVERY analysis:
2000 calls into the OCCT kernel, 2000 parses of a freshly assembled
bundle (12.1s profiled), and 2000 `fallback_op` calls with a mesh check
(10.6s). Shifting ONE body out of 2000 was paying for re-deriving all
2000. Warm analysis: 46.2s -> 21.4s.

THERE CAN BE NO WEAKENING, AND THIS IS CHECKED HERE, NOT DECLARED.
Memory belongs to a bundle INSTANCE, and an instance is born only from
verified bytes: bytes swapped on disk yield either `StoreCorrupt` in
the store or a different instance — one that does not inherit its
memory. Below, three properties are pinned at once: cost (the kernel is
called once), identity of the answer (the second report equals the
first byte-for-byte in its findings), and detachment (editing the
returned value does not change the next answer).
"""
from __future__ import annotations

import pytest

pytest.importorskip("OCP", reason="сцена строится настоящим OCCT")

from kir.project_store import ProjectStore                      # noqa: E402
from kir.clash.project_analysis import analyze_project, reanalyze_after_fix  # noqa: E402


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    import examples.podium_passage as example

    path = tmp_path_factory.mktemp("second") / "scene.sqlite"
    example.save(path)
    return path


class _Kernel:
    """Counts RE-DERIVATIONS — what used to cost 2000 kernel calls per
    analysis.

    What is counted is specifically triangulation, not `read_body`: the
    analysis takes the body's bounding box from its OWN copy of the
    shape (`read_body` promises «independently owned native shape», and
    it cannot be shared — `rederive_preview` cleans it in place). What
    is removed here is exactly what was removed: re-deriving the
    preview and re-parsing the freshly assembled bundle.
    """

    def __init__(self):
        self.calls = 0

    def __enter__(self):
        from kir import occt_geometry as OG

        self.original = OG._triangulate
        counter = self

        def counted(*args, **kwargs):
            counter.calls += 1
            return counter.original(*args, **kwargs)

        OG._triangulate = counted
        return self

    def __exit__(self, *exc):
        from kir import occt_geometry as OG

        OG._triangulate = self.original
        return False


def _shape(report):
    """Report -> a comparable value. `bodies` holds native shapes, and
    those cannot be compared."""
    return {
        "revision": report.revision,
        "program_digest": report.program_digest,
        "tolerance_policy_digest": report.tolerance_policy_digest,
        "bodies_declared": report.bodies_declared,
        "bodies_with_hull": report.bodies_with_hull,
        "bodies_with_geometry": report.bodies_with_geometry,
        "pairs_possible": report.pairs_possible,
        "pairs_compared": report.pairs_compared,
        "search_complete": report.search_complete,
        "hull_source": dict(report.hull_source),
        "source_of_truth": dict(report.source_of_truth),
        "hull_bounds": dict(report.hull_bounds),
        "body_geometry": dict(report.body_geometry),
        "analysis_limits": list(report.analysis_limits),
        "exact": report.exact,
        "broad_phase": dict(report.broad_phase),
        "bodies_in_pairs": dict(report.bodies_in_pairs),
        "not_evaluated": dict(report.not_evaluated),
        "findings": [f.to_dict() for f in report.findings],
    }


def test_a_second_analysis_says_exactly_the_same(scene):
    """🔴 THE MAIN POINT: cheaper does not mean "about something else."
    The reports are compared in full."""
    store = ProjectStore.open(scene)
    first = _shape(analyze_project(store, exact=True))
    second = _shape(reanalyze_after_fix(store, exact=True))
    assert first == second, "второй анализ ответил иначе — память сказала не то же самое"
    # And a COLD handle answers the same way: memory adds nothing to
    # the answer.
    cold = _shape(analyze_project(ProjectStore.open(scene), exact=True))
    assert cold == first, "прогретый и холодный анализ разошлись"


def test_the_kernel_is_called_once_per_body_not_once_per_analysis(scene):
    """A NUMBER: the first analysis reads every body, the second reads
    none."""
    store = ProjectStore.open(scene)
    with _Kernel() as first:
        report = analyze_project(store, exact=True)
    bodies = report.bodies_declared
    assert bodies >= 3, f"тел {bodies} — сцена не та"
    # Every body is derived EXACTLY ONCE over the first analysis.
    assert first.calls == bodies, (first.calls, bodies)
    with _Kernel() as second:
        reanalyze_after_fix(store, exact=True)
    assert second.calls == 0, (
        f"повторный анализ деривировал {second.calls} тел — "
        "передеривация неизменившихся тел не снята")


def test_a_fresh_bundle_does_not_inherit_another_instances_memory(scene):
    """Memory belongs to an INSTANCE: the same bytes in a new instance
    pay again."""
    from kir.occt_geometry import GeometryBundle

    store = ProjectStore.open(scene)
    digest = next(o.geometry.bundle_sha256
                  for _i, o, _x in store.head().addressed_outputs()
                  if o.geometry is not None)
    bundle = store.get_asset(digest)
    with _Kernel() as warm:
        bundle.rederive_preview()
        bundle.rederive_preview()
    assert warm.calls == 1, f"ядро звано {warm.calls} раз на одном экземпляре"
    same_bytes = GeometryBundle.loads(bundle.dumps())
    with _Kernel() as cold:
        same_bytes.rederive_preview()
    assert cold.calls == 1, "новый экземпляр унаследовал чужую память"


def test_a_remembered_answer_is_detached(scene):
    """Editing the returned value does not change the next answer."""
    store = ProjectStore.open(scene)
    digest = next(o.geometry.bundle_sha256
                  for _i, o, _x in store.head().addressed_outputs()
                  if o.geometry is not None)
    derived = store.get_asset(digest).rederive_preview()
    first = derived.fallback_op(name="проверка")
    assert isinstance(first, dict) and "mesh" in first
    inner = first["mesh"]
    key = next(iter(inner)) if isinstance(inner, dict) and inner else None
    first["op"] = "подменено"
    if key is not None:
        inner[key] = "испорчено"
    second = derived.fallback_op(name="проверка")
    assert second.get("op") != "подменено", "память отдала СВОЁ значение наружу"
    if key is not None:
        assert second["mesh"][key] != "испорчено", "память отдала СВОЁ значение наружу"


# ── AFTER THE ACTUAL FIX: WARM REPORT = COLD, BYTE-FOR-BYTE ────────────────
# 🔴 WHY SEPARATE FROM THE PIN ABOVE. That one compares two analyses of
# ONE revision; this one compares against an analysis of a revision
# that DID NOT YET EXIST when the memory was filled. This is exactly
# where memory could lie: the same address, a new body. The "cold"
# answer is taken with clean memory and a fresh handle — that is, by
# the same path a different process would compute it.

def _cold(path, exact=True):
    """The full path: its own bundle memory (a fresh handle) and empty
    address memory."""
    from kir import geometry_materialization as GM

    GM._ADDRESS_MEMO.clear()
    return analyze_project(ProjectStore.open(path), exact=exact)


def _boxed_key(head):
    """A body whose parameters are a box. The podium's are of a
    different kind (it has a void)."""
    for instance in head.instances:
        value = instance.parameters.get(instance.key)
        if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], (list, tuple)):
            return instance.key
    raise AssertionError("в сцене нет тела с коробкой в параметрах")


def _edit_one_body(path, key, shift_mm=250.0):
    """The actual fix: shifting ONE body through a proposal and its
    acceptance."""
    import examples.podium_passage as example
    from kir.project import BodyRepresentation, ModuleInstance, NamedOutput
    from kir.project_merge import ChangeProposal, ProposalScope, accept_proposal

    store = ProjectStore.open(path, readonly=False)
    head = store.head()
    instance = next(item for item in head.instances if item.key == key)
    output = instance.outputs[0]
    box = instance.parameters[key]
    moved = [[box[0][0] + shift_mm, box[0][1], box[0][2]],
             [box[1][0] + shift_mm, box[1][1], box[1][2]]]
    parameters = {**{k: v for k, v in instance.parameters.items()}, key: moved}
    bundle = example.rebuild_body(output.key, moved, parameters,
                                  project_id=head.project_id, instance_key=key)
    new_instance = ModuleInstance(
        instance.key, instance.module_key,
        [NamedOutput(output.key, output.operation,
                     BodyRepresentation(bundle.digest, bundle.body_digest))],
        parameters, metadata=instance.metadata)
    candidate = head.revise(expected_revision=head.revision_id,
                            instances=[new_instance if item.key == key else item
                                       for item in head.instances])
    scope = ProposalScope(instances=(key,))
    accept_proposal(store,
                    ChangeProposal(head, candidate, scope, "test", "сдвиг ради пина"),
                    expected_revision=head.revision_id,
                    authorized_scope=scope, assets=[bundle])
    return store


@pytest.fixture
def editable(tmp_path):
    import examples.podium_passage as example

    path = tmp_path / "editable.sqlite"
    example.save(path)
    return path


def test_after_a_real_edit_the_warm_report_equals_the_cold_one(editable):
    """🔴 F001: memory has NO RIGHT to answer for a body that did not
    exist when it was filled."""
    warm_store = ProjectStore.open(editable)
    before = _shape(analyze_project(warm_store, exact=True))   # filled the memory
    key = _boxed_key(warm_store.head())
    _edit_one_body(editable, key)

    warm = _shape(reanalyze_after_fix(ProjectStore.open(editable), exact=True))
    cold = _shape(_cold(editable))
    assert warm == cold, "после правки тёплый отчёт разошёлся с холодным"
    assert warm["revision"] != before["revision"], "правка не доехала — пин мерил бы не то"
    assert warm["program_digest"] != before["program_digest"], (
        "программа не изменилась от сдвига тела — пин мерил бы не то")


def test_a_swapped_body_of_an_untouched_instance_is_still_refused(editable):
    """🔴 FAIL CONTROL: a transfer by sha does not cancel READING and
    checking the bytes."""
    import sqlite3

    store = ProjectStore.open(editable)
    analyze_project(store, exact=True)                      # warmed up everything that could be warmed
    digests = [o.geometry.bundle_sha256
               for _i, o, _x in store.head().addressed_outputs() if o.geometry is not None]
    connection = sqlite3.connect(editable)
    try:
        payload = connection.execute(
            "SELECT payload FROM geometry_assets WHERE digest=?", (digests[0],)).fetchone()[0]
        connection.execute("UPDATE geometry_assets SET payload=? WHERE digest=?",
                           (payload + " ", digests[0]))
        connection.commit()
    finally:
        connection.close()
    from kir.project_store import StoreCorrupt

    with pytest.raises(StoreCorrupt):
        analyze_project(store, exact=True)
    with pytest.raises(StoreCorrupt):
        analyze_project(ProjectStore.open(editable), exact=True)


def test_a_changed_policy_or_exact_flag_takes_the_full_path(editable):
    """A change of measure is no reason to answer with the old one: the
    report must be a report of THIS measure."""
    store = ProjectStore.open(editable)
    strict = {"clearance_mm": 5000.0}
    a = _shape(analyze_project(store, exact=True))
    b = _shape(analyze_project(store, exact=True, tolerance_policy=strict))
    c = _shape(_cold(editable, exact=False))
    assert b["tolerance_policy_digest"] != a["tolerance_policy_digest"]
    assert b == _shape(_cold_policy(editable, strict)), "политика: тёплый ≠ холодный"
    assert c["exact"] is False and a["exact"] is True


def _cold_policy(path, policy):
    from kir import geometry_materialization as GM

    GM._ADDRESS_MEMO.clear()
    return analyze_project(ProjectStore.open(path), exact=True, tolerance_policy=policy)
