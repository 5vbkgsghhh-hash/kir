"""THE DISPLAY SCENE AND ITS ANALYSIS TAKE ONE REVISION SNAPSHOT, NOT TWO.

🔴 TWO NUMBERS THAT SET UP THIS FILE (08.09.2026, direction S, N=2000 real
OCCT bodies, frozen copy `3e1bc77`).

1. BODIES WERE READ ONE AT A TIME. `export_saved_project_scene` assembled
   the bundle set with a dict using `store.get_asset(...)` for EACH body —
   2000 transactions, and in each one `_read_state` re-checked ALL of the
   head's assets from scratch: **22.79 s** against **0.229 s** for a single
   `get_assets` batch (99×). The same lever was pulled in `analyze_project`
   on 07.09 and never reached the viewer.
2. MATERIALIZATION WAS DONE TWICE. The viewer built it for the scene, and
   then `analyze_project` reopened the store, read the same bodies again,
   and built it a SECOND time from the same bytes: a cold materialization
   of 2000 bodies — **28.8 s**.

There is no weakening, and it is guarded by `_check_snapshot`: the accepted
snapshot is checked by revision, completeness, and body digests at EVERY
address. The FAIL controls below feed it a snapshot from a different
revision, and a snapshot referring to a different body.
"""
from __future__ import annotations

import pytest

from kir.viewer import standalone_export as export

pytest.importorskip("OCP", reason="сцена приёмки строится настоящим кернелом")


@pytest.fixture(scope="module")
def saved(tmp_path_factory):
    from examples.podium_passage import save
    return save(tmp_path_factory.mktemp("one-snapshot") / "store")


def _scene_without_timing(artifact):
    """Scene bytes WITHOUT the duration field — and here is why it is
    subtracted out.

    🔴 THE DISPLAY ARTIFACT IS NOT A FUNCTION OF THE PROJECT, AND THIS IS
    NOT MY FIX (verified on a clean `3e1bc77`): `timing_ms.total` — the
    wall-clock build time — travels into the scene. Two calls in a row on
    THE SAME store gave 511.7 ms and 8.8 ms, that is, DIFFERENT bytes and a
    different `artifact_digest` for one and the same project. So the
    equality of the paths is checked against everything except the
    duration; the duration itself is named as a separate finding, not swept
    under the test.
    """
    import base64
    import json
    import struct

    data = json.loads(artifact.dumps())
    raw = base64.b64decode(data["scene"]["base64"])
    size = struct.unpack("<I", raw[8:12])[0]
    body = json.loads(raw[12:12 + size].decode("utf-8"))
    body.pop("timing_ms", None)
    data.pop("artifact_digest", None)
    data["scene"] = {"tail_bytes": len(raw) - 12 - size, "body": body}
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def test_the_scene_reads_every_body_in_one_transaction(saved):
    """The number: `get_asset` one at a time — ZERO calls, the batch — one."""
    from kir.project_store import ProjectStore

    single, batch = [], []
    one, many = ProjectStore.get_asset, ProjectStore.get_assets
    try:
        ProjectStore.get_asset = lambda self, digest: (single.append(digest), one(self, digest))[1]
        ProjectStore.get_assets = lambda self, digests: (batch.append(tuple(digests)), many(self, digests))[1]
        export.export_saved_project_scene(saved, exact=True)
    finally:
        ProjectStore.get_asset, ProjectStore.get_assets = one, many
    assert len(batch) == 1, ("сцена обязана взять тела ОДНИМ пакетом", batch)
    assert single == [], ("поштучное чтение вернулось — рычаг снят", single)
    assert len(batch[0]) >= 1


def test_the_scene_is_the_same_as_the_one_built_by_two_materializations(saved):
    """Scene bytes (except duration) are the same as on the old path."""
    from kir.clash.project_analysis import analyze_project
    from kir.geometry_materialization import materialize_project
    from kir.project_store import ProjectStore
    from kir.viewer.clash_findings import CLASH_CAPABILITY

    now, _ = export.export_saved_project_scene(saved, exact=True)
    store = ProjectStore.open(saved.path) if hasattr(saved, "path") else saved
    project = store.head()
    bundles = {output.geometry.bundle_sha256: store.get_asset(output.geometry.bundle_sha256)
               for _instance, output, _oid in project.geometry_references()}
    materialization = materialize_project(project, bundles)
    report = analyze_project(store, None, exact=True)
    before = export.export_standalone_scene(materialization,
                                            consumer_capabilities=[CLASH_CAPABILITY],
                                            clash_report=report.to_dict())
    assert _scene_without_timing(now) == _scene_without_timing(before)


def test_a_snapshot_of_another_revision_is_refused_by_name(saved):
    """FAIL control: a snapshot of a foreign revision is not accepted
    silently."""
    from kir.clash.project_analysis import ProjectAnalysisError, analyze_revision
    from kir.geometry_materialization import materialize_project
    from kir.project import ModuleInstance
    from kir.project_store import ProjectStore

    store = ProjectStore.open(saved.path) if hasattr(saved, "path") else saved
    project = store.head()
    bundles = {output.geometry.bundle_sha256: store.get_asset(output.geometry.bundle_sha256)
               for _instance, output, _oid in project.geometry_references()}
    stranger = project.revise(
        expected_revision=project.revision_id,
        instances=[ModuleInstance(item.key, item.module_key, list(item.outputs),
                                  dict(item.parameters),
                                  metadata={**dict(item.metadata or {}), "note": "чужая"})
                   if index == 0 else item
                   for index, item in enumerate(project.instances)])
    foreign = materialize_project(stranger, bundles)
    assert foreign.project.revision_id != project.revision_id
    with pytest.raises(ProjectAnalysisError, match="another project revision"):
        analyze_revision(project, lambda digest: bundles[digest], exact=False,
                         materialized=foreign)


def test_a_snapshot_that_cites_another_body_is_refused_by_name(saved):
    """FAIL control: a swapped body digest in a snapshot row is a refusal."""
    from kir.clash.project_analysis import ProjectAnalysisError, analyze_revision
    from kir.geometry_materialization import GeometryMaterialization, materialize_project
    from kir.project_store import ProjectStore

    store = ProjectStore.open(saved.path) if hasattr(saved, "path") else saved
    project = store.head()
    bundles = {output.geometry.bundle_sha256: store.get_asset(output.geometry.bundle_sha256)
               for _instance, output, _oid in project.geometry_references()}
    honest = materialize_project(project, bundles)
    rows = [dict(row) for row in honest.sources]
    rows[0]["source_bundle_sha256"] = "0" * 64
    forged = GeometryMaterialization.__new__(GeometryMaterialization)
    object.__setattr__(forged, "project", honest.project)
    object.__setattr__(forged, "program", honest.program)
    object.__setattr__(forged, "planned", honest.planned)
    object.__setattr__(forged, "sources", tuple(rows))
    object.__setattr__(forged, "selection", None)
    object.__setattr__(forged, "_born_here", False)
    with pytest.raises(ProjectAnalysisError, match="cites another body"):
        analyze_revision(project, lambda digest: bundles[digest], exact=False,
                         materialized=forged)


def test_a_snapshot_of_a_selection_is_not_an_analysis_of_the_whole(saved):
    """FAIL control: a snapshot of PART of the project cannot be an
    analysis of the whole."""
    from kir.clash.project_analysis import ProjectAnalysisError, analyze_revision
    from kir.geometry_materialization import GeometryMaterialization, materialize_project
    from kir.project_store import ProjectStore

    store = ProjectStore.open(saved.path) if hasattr(saved, "path") else saved
    project = store.head()
    bundles = {output.geometry.bundle_sha256: store.get_asset(output.geometry.bundle_sha256)
               for _instance, output, _oid in project.geometry_references()}
    honest = materialize_project(project, bundles)
    partial = GeometryMaterialization.__new__(GeometryMaterialization)
    for name in ("project", "program", "planned", "sources"):
        object.__setattr__(partial, name, getattr(honest, name))
    object.__setattr__(partial, "selection", object())
    object.__setattr__(partial, "_born_here", False)
    with pytest.raises(ProjectAnalysisError, match="selection"):
        analyze_revision(project, lambda digest: bundles[digest], exact=False,
                         materialized=partial)
