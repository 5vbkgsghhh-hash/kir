"""Explicit store evolution and body assets share the existing SQLite owner."""
from __future__ import annotations

import sqlite3
import json
import multiprocessing
import os
import subprocess
import sys

import pytest

from kir.project_store import (
    GEOMETRY_STORE_SCHEMA, STORE_SCHEMA, ProjectStore, ProjectStoreError,
    StoreCommitUnknown, StoreConflict, StoreCorrupt, StoreReadOnly,
    StoreAssetMissing, StoreNotFound, StoreRecoveryRequired, StoreUpgradeRequired,
)
from kir.tests.test_project_store import root, changed


def stored_rows(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT * FROM revisions ORDER BY sequence").fetchall()


def test_upgrade_changes_only_storage_schema_not_authored_payload_or_head(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", first)
    second = changed(first)
    store.commit(second, expected_revision=first.revision_id)
    before = stored_rows(store.path)
    readonly = ProjectStore.open(store.path)
    assert readonly.schema == STORE_SCHEMA
    assert store.upgrade_schema(GEOMETRY_STORE_SCHEMA, expected_revision=second.revision_id)
    assert readonly.schema == GEOMETRY_STORE_SCHEMA
    assert readonly.store_id == store.store_id
    assert readonly.head().dumps() == second.dumps()
    assert stored_rows(store.path) == before
    assert [item.dumps() for item in readonly.history()] == [first.dumps(), second.dumps()]
    assert not store.upgrade_schema(GEOMETRY_STORE_SCHEMA, expected_revision=second.revision_id)
    third = changed(second)
    assert store.commit(third, expected_revision=second.revision_id).inserted
    assert ProjectStore.open(store.path).get(first.revision_id).dumps() == first.dumps()


def test_create_v2_is_explicit_and_keeps_v1_project_bytes(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", first, schema=GEOMETRY_STORE_SCHEMA)
    assert store.schema == GEOMETRY_STORE_SCHEMA
    assert store.head().dumps() == first.dumps()
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM geometry_assets").fetchone() == (0,)


@pytest.mark.parametrize("schema", ["future", "kir-project-store/0", None, True, {}])
def test_unknown_creation_schema_does_not_create_file(tmp_path, schema):
    path = tmp_path / "project.sqlite"
    with pytest.raises(ProjectStoreError, match="schema"):
        ProjectStore.create(path, root(), schema=schema)
    assert not path.exists()


def test_readonly_stale_and_downgrade_requests_leave_bytes_unchanged(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", first)
    before = store.path.read_bytes()
    with pytest.raises(StoreReadOnly):
        ProjectStore.open(store.path).upgrade_schema(GEOMETRY_STORE_SCHEMA, expected_revision=first.revision_id)
    with pytest.raises(StoreConflict):
        store.upgrade_schema(GEOMETRY_STORE_SCHEMA, expected_revision="a" * 64)
    with pytest.raises(ProjectStoreError):
        store.upgrade_schema(STORE_SCHEMA, expected_revision=first.revision_id)
    assert store.path.read_bytes() == before
    store.upgrade_schema(GEOMETRY_STORE_SCHEMA, expected_revision=first.revision_id)
    after = store.path.read_bytes()
    with pytest.raises(ProjectStoreError):
        store.upgrade_schema(STORE_SCHEMA, expected_revision=first.revision_id)
    assert store.path.read_bytes() == after


class UpgradeFault:
    def __init__(self, connection, phase):
        self.connection, self.phase = connection, phase

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args):
        result = self.connection.execute(sql, *args)
        if ((self.phase == "table" and sql.startswith("CREATE TABLE geometry_assets"))
                or (self.phase == "owner" and sql.startswith("UPDATE project_store SET schema_version"))
                or (self.phase == "header" and sql == "PRAGMA user_version=2")
                or (self.phase == "ack" and sql == "COMMIT")):
            raise sqlite3.OperationalError("injected upgrade failure")
        return result


@pytest.mark.parametrize("phase", ["table", "owner", "header", "ack"])
def test_schema_upgrade_is_atomic_including_lost_ack(tmp_path, monkeypatch, phase):
    import kir.project_store as module

    first = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", first)
    rows = stored_rows(store.path)
    original = module._connect
    with monkeypatch.context() as patch:
        patch.setattr(module, "_connect", lambda *args, **kwargs:
                      UpgradeFault(original(*args, **kwargs), phase))
        error = StoreCommitUnknown if phase == "ack" else ProjectStoreError
        with pytest.raises(error):
            store.upgrade_schema(GEOMETRY_STORE_SCHEMA, expected_revision=first.revision_id)
    assert stored_rows(store.path) == rows
    assert store.schema == (GEOMETRY_STORE_SCHEMA if phase == "ack" else STORE_SCHEMA)
    assert store.upgrade_schema(GEOMETRY_STORE_SCHEMA, expected_revision=first.revision_id) is (phase != "ack")
    assert store.head().dumps() == first.dumps()


@pytest.mark.parametrize("mutation", [
    "PRAGMA user_version=1",
    "UPDATE project_store SET schema_version='kir-project-store/1'",
    "DROP TABLE geometry_assets",
    "CREATE TRIGGER injected AFTER INSERT ON geometry_assets BEGIN SELECT 1; END",
])
def test_partial_or_foreign_v2_schema_is_not_adopted(tmp_path, mutation):
    store = ProjectStore.create(tmp_path / "project.sqlite", root(), schema=GEOMETRY_STORE_SCHEMA)
    with sqlite3.connect(store.path) as connection:
        connection.execute(mutation)
    before = store.path.read_bytes()
    with pytest.raises(StoreCorrupt):
        ProjectStore.open(store.path)
    assert store.path.read_bytes() == before


@pytest.fixture
def body_factory():
    native = pytest.importorskip("OCP.BRepPrimAPI", reason="optional real OCCT fixture")
    from kir.occt_geometry import capture_body
    from kir.project import RecipePin

    def build(width=1000, *, project_id="geometry-project", source="def build(): pass"):
        return capture_body(native.BRepPrimAPI_MakeBox(width, 2000, 3000).Shape(),
            project_id=project_id, instance_key="i", output_key="body",
            recipe=RecipePin(source, "a" * 64), parameters={"width_mm": width})
    return build


def instance_for(asset, **kwargs):
    from kir.project import BodyRepresentation, ModuleInstance, NamedOutput

    return ModuleInstance("i", "m", [NamedOutput("body",
        {"op": "create_directshape", "name": "Body", "category": "mass"},
        BodyRepresentation(asset.digest, asset.body_digest))],
        parameters=asset.to_dict()["manifest"]["parameters"], **kwargs)


def geometry_root(asset=None, *, project_id="geometry-project"):
    from kir.project import ModuleDefinition, ProjectRevision, PROJECT_SCHEMA_V2, RecipePin

    recipe = None if asset is None else RecipePin.from_dict(asset.to_dict()["manifest"]["recipe"])
    return ProjectRevision(project_id, [ModuleDefinition("m", "sealed_evaluation", recipe)],
        [] if asset is None else [instance_for(asset)], schema=PROJECT_SCHEMA_V2)


def assets_on_disk(path):
    with sqlite3.connect(path) as connection:
        return dict(connection.execute("SELECT digest, payload FROM geometry_assets"))


def test_body_root_requires_explicit_store_v2_and_all_assets_before_file_creation(tmp_path, body_factory):
    asset = body_factory()
    first = geometry_root(asset)
    path = tmp_path / "geometry.sqlite"
    with pytest.raises(StoreUpgradeRequired):
        ProjectStore.create(path, first, assets=[asset])
    assert not path.exists()
    with pytest.raises(StoreAssetMissing):
        ProjectStore.create(path, first, schema=GEOMETRY_STORE_SCHEMA)
    assert not path.exists()
    store = ProjectStore.create(path, first, schema=GEOMETRY_STORE_SCHEMA, assets=[asset])
    assert store.get_asset(asset.digest).dumps() == asset.dumps()
    assert store.head().dumps() == first.dumps()
    assert assets_on_disk(path) == {asset.digest: asset.dumps()}


def test_unchanged_asset_is_stored_once_across_history_and_exact_redelivery(tmp_path, body_factory):
    asset = body_factory()
    first = geometry_root(asset)
    store = ProjectStore.create(tmp_path / "geometry.sqlite", first,
                                schema=GEOMETRY_STORE_SCHEMA, assets=[asset, asset])
    second = changed(first)
    store.commit(second, expected_revision=first.revision_id)
    third = changed(second, "third")
    store.commit(third, expected_revision=second.revision_id, assets=[asset])
    receipt = store.commit(second, expected_revision=first.revision_id, assets=[asset])
    assert not receipt.inserted and receipt.head_revision == third.revision_id
    assert len(store.history()) == 3
    assert assets_on_disk(store.path) == {asset.digest: asset.dumps()}


def test_upgrading_existing_store_does_not_implicitly_upgrade_authored_schema(tmp_path, body_factory):
    from kir.project import ModuleDefinition, ProjectRevision, PROJECT_SCHEMA_V2

    first = ProjectRevision("geometry-project", [ModuleDefinition("m")], [])
    store = ProjectStore.create(tmp_path / "geometry.sqlite", first)
    upgraded = first.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=first.revision_id)
    store.commit(upgraded, expected_revision=first.revision_id)  # no body yet
    asset = body_factory()
    proposal = upgraded.with_instances([instance_for(asset)], expected_revision=upgraded.revision_id)
    before = stored_rows(store.path)
    with pytest.raises(StoreUpgradeRequired):
        store.commit(proposal, expected_revision=upgraded.revision_id, assets=[asset])
    assert stored_rows(store.path) == before
    store.upgrade_schema(GEOMETRY_STORE_SCHEMA, expected_revision=upgraded.revision_id)
    assert store.head().dumps() == upgraded.dumps()
    store.commit(proposal, expected_revision=upgraded.revision_id, assets=[asset])
    assert store.get(first.revision_id).dumps() == first.dumps()
    assert len(store.history()) == 3


@pytest.mark.parametrize("failure", ["missing", "foreign_project", "wrong_parameters", "wrong_recipe", "extra"])
def test_invalid_asset_proposal_never_leaks_asset_or_revision(tmp_path, body_factory, failure):
    import dataclasses
    from kir.project import ModuleDefinition, RecipePin

    first = geometry_root()
    store = ProjectStore.create(tmp_path / "geometry.sqlite", first, schema=GEOMETRY_STORE_SCHEMA)
    asset = body_factory(project_id="other" if failure == "foreign_project" else first.project_id)
    instance = instance_for(asset)
    if failure == "wrong_parameters":
        instance = dataclasses.replace(instance, parameters={"width_mm": 2000})
    proposal = first.with_instances([instance], expected_revision=first.revision_id)
    if failure == "wrong_recipe":
        proposal = first.revise(expected_revision=first.revision_id,
            modules=[ModuleDefinition("m", "sealed_evaluation", RecipePin("different source", "b" * 64))],
            instances=[instance])
    supplied = [] if failure == "missing" else [asset]
    if failure == "extra":
        supplied.append(body_factory(3000))
    with pytest.raises(ProjectStoreError):
        store.commit(proposal, expected_revision=first.revision_id, assets=supplied)
    assert store.head().dumps() == first.dumps()
    assert len(store.history()) == 1 and assets_on_disk(store.path) == {}


@pytest.mark.parametrize("phase", ["asset", "revision", "head", "ack"])
def test_asset_and_revision_cas_share_one_failure_boundary(tmp_path, body_factory, monkeypatch, phase):
    import kir.project_store as module

    first = geometry_root()
    asset = body_factory()
    proposal = first.with_instances([instance_for(asset)], expected_revision=first.revision_id)
    store = ProjectStore.create(tmp_path / "geometry.sqlite", first, schema=GEOMETRY_STORE_SCHEMA)
    original = module._connect

    class Fault:
        def __init__(self, connection):
            self.connection = connection
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def execute(self, sql, *args):
            result = self.connection.execute(sql, *args)
            if ((phase == "asset" and sql.startswith("INSERT INTO geometry_assets"))
                    or (phase == "revision" and sql.startswith("INSERT INTO revisions"))
                    or (phase == "head" and sql.startswith("UPDATE project_store SET head_revision"))
                    or (phase == "ack" and sql == "COMMIT")):
                raise sqlite3.OperationalError("injected atomic asset failure")
            return result

    with monkeypatch.context() as patch:
        patch.setattr(module, "_connect", lambda *args, **kwargs: Fault(original(*args, **kwargs)))
        with pytest.raises(StoreCommitUnknown if phase == "ack" else ProjectStoreError):
            store.commit(proposal, expected_revision=first.revision_id, assets=[asset])
    assert store.head().revision_id == (proposal if phase == "ack" else first).revision_id
    assert assets_on_disk(store.path) == ({asset.digest: asset.dumps()} if phase == "ack" else {})
    assert store.commit(proposal, expected_revision=first.revision_id, assets=[asset]).inserted is (phase != "ack")
    assert len(store.history()) == 2


@pytest.mark.parametrize("mutation", ["DELETE FROM geometry_assets", "UPDATE geometry_assets SET payload='{}'"])
def test_missing_or_corrupt_stored_asset_is_not_repaired_by_retry(tmp_path, body_factory, mutation):
    """🔴 WHAT THIS PIN USED TO MEASURE AND WHY IT CHANGED (07.09.2026).

    It used to require a refusal from FIVE paths at once, including
    `head()` and `get(revision)`. This was pinning down behavior that
    CONTRADICTED the rule declared in the module's header ("Hot paths
    validate schema, ownership, head and the addressed payload, not
    every old snapshot"): a hot read was walking ALL of the head's
    assets. The cost was measured: `(N+2)·M` reads — exactly 499 140 on
    705 bodies, 74 % of analysis time, and ~2.3 hours on 10 000 bodies by
    the model.

    The pin's subject — "a retry does NOT fix corruption" — stayed the
    same and is still checked. What changed is the LIST of paths:
    reaching a CORRUPTED body (`get_asset`), a full walk (`history`), and
    a WRITE (`commit`) refuse, as before; `head()` and `get(revision)`
    now read the header without touching the bodies — and this too is
    PINNED below, so the declared behavior does not stay unspoken.
    """
    asset = body_factory()
    first = geometry_root(asset)
    store = ProjectStore.create(tmp_path / "geometry.sqlite", first,
                                schema=GEOMETRY_STORE_SCHEMA, assets=[asset])
    with sqlite3.connect(store.path) as connection:
        connection.execute(mutation)
    before = store.path.read_bytes()
    for action in (store.history,
                   lambda: store.get_asset(asset.digest),
                   lambda: store.commit(first, expected_revision=None, assets=[asset])):
        with pytest.raises(StoreCorrupt):
            action()
    # The declared behavior of a hot read — pinned, not left silent.
    assert store.head().revision_id == first.revision_id
    assert store.get(first.revision_id).revision_id == first.revision_id
    assert store.path.read_bytes() == before


def test_inert_load_lookup_and_history_in_fresh_process_with_native_imports_forbidden(tmp_path, body_factory):
    asset = body_factory(source="raise RuntimeError('saved source must never execute')")
    first = geometry_root(asset)
    store = ProjectStore.create(tmp_path / "geometry.sqlite", first,
                                schema=GEOMETRY_STORE_SCHEMA, assets=[asset])
    script = """
import importlib.abc, json, sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('native import during inert storage access')
sys.meta_path.insert(0, NoNative())
from kir.project_store import ProjectStore
path, digest = json.loads(sys.stdin.read())
s = ProjectStore.open(path)
assert len(s.history()) == 1
assert s.get(s.head().revision_id).revision_id == s.head().revision_id
print(s.get_asset(digest).digest)
"""
    result = subprocess.run([sys.executable, "-c", script], text=True,
        input=json.dumps([str(store.path), asset.digest]), capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == asset.digest


def _asset_writer(path, project_json, asset_json, start, result):
    from kir.project import ProjectRevision
    from kir.occt_geometry import GeometryBundle
    try:
        store = ProjectStore.open(path, readonly=False)
        proposal, asset = ProjectRevision.loads(project_json), GeometryBundle.loads(asset_json)
        result.put(("ready", os.getpid()))
        if not start.wait(10):
            raise RuntimeError("barrier timeout")
        receipt = store.commit(proposal, expected_revision=proposal.parent_revision, assets=[asset])
        result.put(("committed", receipt.inserted, receipt.revision_id))
    except Exception as exc:
        result.put((type(exc).__name__, str(exc)))


@pytest.mark.parametrize("same", [False, True])
def test_two_real_processes_cannot_leave_losing_geometry_assets(tmp_path, body_factory, same):
    first = geometry_root()
    store = ProjectStore.create(tmp_path / "geometry.sqlite", first, schema=GEOMETRY_STORE_SCHEMA)
    left, right = body_factory(1000), body_factory(2000)
    if same:
        right = left
    proposals = [first.with_instances([instance_for(asset)], expected_revision=first.revision_id)
                 for asset in (left, right)]
    context = multiprocessing.get_context("spawn")
    start, result = context.Event(), context.Queue()
    processes = [context.Process(target=_asset_writer,
        args=(str(store.path), proposal.dumps(), asset.dumps(), start, result))
        for proposal, asset in zip(proposals, (left, right))]
    try:
        for process in processes:
            process.start()
        assert all(result.get(timeout=20)[0] == "ready" for _ in processes)
        start.set()
        outcomes = [result.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(20)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        result.close()
    if same:
        assert all(row[0] == "committed" for row in outcomes), outcomes
        assert sorted(row[1] for row in outcomes) == [False, True]
    else:
        assert sorted(row[0] for row in outcomes) == ["StoreConflict", "committed"], outcomes
    assert len(store.history()) == 2 and len(assets_on_disk(store.path)) == 1
    referenced = store.head().geometry_references()[0][1].geometry.bundle_sha256
    assert set(assets_on_disk(store.path)) == {referenced}


def test_asset_lookup_is_detached_and_missing_or_invalid_ids_refuse(tmp_path, body_factory):
    asset = body_factory()
    store = ProjectStore.create(tmp_path / "geometry.sqlite", geometry_root(asset),
                                schema=GEOMETRY_STORE_SCHEMA, assets=[asset])
    loaded = store.get_asset(asset.digest)
    detached = loaded.to_dict()
    detached["manifest"]["parameters"]["width_mm"] = 99
    assert loaded.dumps() == asset.dumps() == store.get_asset(asset.digest).dumps()
    for identity in (None, True, "bad", "b" * 64):
        with pytest.raises(StoreNotFound):
            store.get_asset(identity)
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO geometry_assets VALUES (NULL, '{}')")


def test_history_audits_old_assets_but_head_does_not_scan_unreferenced_past_bodies(tmp_path, body_factory):
    asset = body_factory()
    first = geometry_root(asset)
    store = ProjectStore.create(tmp_path / "geometry.sqlite", first,
                                schema=GEOMETRY_STORE_SCHEMA, assets=[asset])
    no_body = first.with_instances([], expected_revision=first.revision_id)
    store.commit(no_body, expected_revision=first.revision_id)
    assert len(store.history()) == 2  # retained old asset is still reachable
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE geometry_assets SET payload='{}'")
    assert store.head().dumps() == no_body.dumps()
    with pytest.raises(StoreCorrupt):
        store.history()
    # 🔴 CHANGED ON 07.09.2026 TOGETHER WITH THE HEADER RULE. There used
    # to be a refusal here from `get(first.revision_id)`: a hot read was
    # walking every asset of the addressed revision. Now `get` reads the
    # revision's header without touching its bodies — exactly what this
    # pin's name asserts about `head`. A full walk is still reachable
    # through the existing name `history()` (line above), and that is
    # what catches corruption. Returning the revision is pinned down so
    # that "does not refuse" does not turn into "silently does nothing".
    assert store.get(first.revision_id).dumps() == first.dumps()
    # And reaching the body ITSELF still refuses: the addressed payload
    # is always checked, and this is the other half of the header's rule.
    with pytest.raises(StoreCorrupt):
        store.get_asset(asset.digest)


def _asset_crash_writer(path, project_json, asset_json, phase):
    import kir.project_store as module
    from kir.project import ProjectRevision
    from kir.occt_geometry import GeometryBundle

    original = module._connect
    class Crash:
        def __init__(self, connection):
            self.connection = connection
            connection.execute("PRAGMA cache_size=1")
            connection.execute("PRAGMA cache_spill=ON")
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def execute(self, sql, *args):
            result = self.connection.execute(sql, *args)
            if ((phase == "asset" and sql.startswith("INSERT INTO geometry_assets"))
                    or (phase == "revision" and sql.startswith("INSERT INTO revisions"))):
                os._exit(74)
            if phase == "commit" and sql == "COMMIT":
                os._exit(75)
            return result
    module._connect = lambda *args, **kwargs: Crash(original(*args, **kwargs))
    store = ProjectStore.open(path, readonly=False)
    proposal = ProjectRevision.loads(project_json)
    asset = GeometryBundle.loads(asset_json)
    store.commit(proposal, expected_revision=proposal.parent_revision, assets=[asset])
    os._exit(99)


@pytest.mark.parametrize("phase", ["asset", "revision", "commit"])
def test_real_crash_cannot_commit_half_a_geometry_revision(tmp_path, body_factory, phase):
    first = geometry_root()
    store = ProjectStore.create(tmp_path / "geometry.sqlite", first, schema=GEOMETRY_STORE_SCHEMA)
    asset = body_factory(source="# inert recipe padding\n" + "#" * 250000)
    proposal = first.with_instances([instance_for(asset)], expected_revision=first.revision_id)
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_asset_crash_writer,
        args=(str(store.path), proposal.dumps(), asset.dumps(), phase))
    process.start()
    process.join(20)
    if process.is_alive():
        process.terminate()
        process.join(5)
    assert process.exitcode == (75 if phase == "commit" else 74)
    if phase != "commit":
        before = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
        with pytest.raises(StoreRecoveryRequired):
            ProjectStore.open(store.path)
        assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before
    recovered = ProjectStore.open(store.path, readonly=False)
    assert recovered.head().revision_id == (proposal if phase == "commit" else first).revision_id
    assert set(assets_on_disk(store.path)) == ({asset.digest} if phase == "commit" else set())
    assert recovered.commit(proposal, expected_revision=first.revision_id, assets=[asset]).inserted is (phase != "commit")
    assert len(recovered.history()) == 2


def test_authored_schema_cannot_silently_downgrade_in_an_existing_history(tmp_path):
    from kir.project import ProjectRevision, PROJECT_SCHEMA_V2

    first = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", first)
    upgraded = first.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=first.revision_id)
    store.commit(upgraded, expected_revision=first.revision_id)
    # A standalone constructor cannot know the actual schema of a hash-named
    # parent. The shared history owner can and must reject the downgrade edge.
    downgrade = ProjectRevision(first.project_id, first.modules, first.instances,
                                 parent_revision=upgraded.revision_id)
    with pytest.raises(StoreConflict, match="downgrade"):
        store.commit(downgrade, expected_revision=upgraded.revision_id)
    assert len(store.history()) == 2
    # Simulate an external database modification, not an authorized API path.
    with sqlite3.connect(store.path) as connection:
        connection.execute("INSERT INTO revisions VALUES (2, ?, ?, ?, ?)",
            (downgrade.revision_id, downgrade.project_id, downgrade.parent_revision, downgrade.dumps()))
        connection.execute("UPDATE project_store SET head_revision=?", (downgrade.revision_id,))
    with pytest.raises(StoreCorrupt, match="downgrade"):
        store.history()


def test_reopened_store_materializes_from_body_not_its_rehashed_stale_preview(tmp_path, body_factory):
    import struct
    from kir import compile_program
    from kir.geometry_materialization import materialize_project
    from kir.occt_geometry import GeometryBundle
    from kir.project import _hash
    from kir.viewer.codec import SCENE_MAGIC
    from kir.viewer.live_scene import scene_from_programs

    body, old_preview = body_factory(2000), body_factory(1000)
    mixed = body.to_dict()
    old = old_preview.to_dict()
    mixed["preview_mesh"] = old["preview_mesh"]
    mixed["manifest"]["preview"]["sha256"] = _hash(mixed["preview_mesh"])
    mixed["manifest"]["measurements"] = old["manifest"]["measurements"]
    mixed["bundle_sha256"] = _hash({k: v for k, v in mixed.items() if k != "bundle_sha256"})
    asset = GeometryBundle(mixed)
    project = geometry_root(asset)
    path = tmp_path / "geometry.sqlite"
    ProjectStore.create(path, project, schema=GEOMETRY_STORE_SCHEMA, assets=[asset])
    store = ProjectStore.open(path)
    loaded = store.get_asset(asset.digest)
    assert max(point[0] for point in loaded.to_dict()["preview_mesh"]["vertices_mm"]) == 1000
    realized = materialize_project(store.head(), {loaded.digest: loaded})
    program = realized.to_program()
    operation = program["ops"][0]
    assert max(point[0] for point in operation["mesh"]["vertices_mm"]) == 2000
    assert realized.sources[0]["measurements"]["volume_mm3"] == pytest.approx(12_000_000_000)
    assert realized.sources[0]["stored_preview_bytes_equal"] is False
    blob, meta = scene_from_programs([program], doc_key="offline representation only")
    header_size = struct.unpack_from("<I", blob, len(SCENE_MAGIC))[0]
    at = len(SCENE_MAGIC) + 4
    header = json.loads(blob[at:at + header_size])
    assert meta["mesh_shown"] == 1 and meta["mesh_refused"] == {}
    assert header["counts"]["mesh_triangles"] == len(operation["mesh"]["triangles"])
    assert header["counts"]["box"] == 0
    for version in ("2023", "2026"):
        result = compile_program(realized.planned, revit_version=version, bulk=False)
        assert result.ok, result.diagnostics
        assert result.planned.plan_digest == realized.planned.plan_digest
    assert store.get_asset(asset.digest).dumps() == asset.dumps()
    assert store.head().dumps() == project.dumps()


@pytest.mark.parametrize("creating", [False, True])
def test_storage_validates_decoded_snapshot_not_overridden_reference_iterator(tmp_path, body_factory, creating):
    from kir.project import ProjectRevision

    class NoGeometry(ProjectRevision):
        def geometry_references(self):
            return ()

    asset = body_factory()
    first = geometry_root()
    proposal = (geometry_root(asset) if creating else
                first.with_instances([instance_for(asset)], expected_revision=first.revision_id))
    disguised = NoGeometry(proposal.project_id, proposal.modules, proposal.instances,
        proposal.intent, proposal.metadata, proposal.parent_revision, proposal.ir_version,
        schema=proposal.schema)
    assert disguised.dumps() == proposal.dumps()
    path = tmp_path / "geometry.sqlite"
    if creating:
        with pytest.raises(StoreAssetMissing):
            ProjectStore.create(path, disguised, schema=GEOMETRY_STORE_SCHEMA)
        assert not path.exists()
        store = ProjectStore.create(path, disguised, schema=GEOMETRY_STORE_SCHEMA, assets=[asset])
    else:
        store = ProjectStore.create(path, first, schema=GEOMETRY_STORE_SCHEMA)
        before = stored_rows(path)
        with pytest.raises(StoreAssetMissing):
            store.commit(disguised, expected_revision=first.revision_id)
        assert stored_rows(path) == before and assets_on_disk(path) == {}
        assert store.commit(disguised, expected_revision=first.revision_id, assets=[asset]).inserted
    assert type(store.head()) is ProjectRevision
    assert store.head().dumps() == proposal.dumps()
    assert store.get_asset(asset.digest).dumps() == asset.dumps()
