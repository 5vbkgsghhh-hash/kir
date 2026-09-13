"""SQLite authoring history: real persistence, processes and failure boundaries."""
from __future__ import annotations

import dataclasses
import multiprocessing
import os
import sqlite3

import pytest

from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, RecipePin
from kir.project_store import (
    ProjectStore, ProjectStoreError, StoreBusy, StoreCommitUnknown, StoreConflict,
    StoreCorrupt, StoreExists, StoreNotFound, StoreReadOnly, StoreRecoveryRequired,
)


def root(*, project_id="project", intent="base", metadata=None):
    return ProjectRevision(
        project_id, (ModuleDefinition("m"),),
        (ModuleInstance("i", "m", {"level": {
            "op": "create_level", "name": "Ground", "elev_mm": 0}}),),
        intent=intent, metadata={} if metadata is None else metadata)


def changed(base, intent="changed", **kwargs):
    return base.revise(expected_revision=base.revision_id, intent=intent, **kwargs)


def raw_count(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT count(*) FROM revisions").fetchone()[0]


def alter(path, sql, params=()):
    with sqlite3.connect(path) as connection:
        connection.execute(sql, params)


def test_create_reopen_history_and_lookup_preserve_the_exact_snapshots(tmp_path):
    path = tmp_path / "project.sqlite"
    first = root()
    store = ProjectStore.create(path, first)
    second = changed(first)
    result = store.commit(second, expected_revision=first.revision_id)
    assert result.inserted is True
    assert result.revision_id == result.head_revision == second.revision_id
    reopened = ProjectStore.open(path)
    assert reopened.readonly is True
    assert reopened.project_id == first.project_id
    assert reopened.store_id == store.store_id
    assert reopened.head().dumps() == second.dumps()
    assert reopened.get(first.revision_id).dumps() == first.dumps()
    assert tuple(item.dumps() for item in reopened.history()) == (first.dumps(), second.dumps())
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.inserted = False
    assert raw_count(path) == 2
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("readonly", [True, False])
def test_open_missing_database_never_creates_any_file(tmp_path, readonly):
    path = tmp_path / "missing.sqlite"
    before = tuple(tmp_path.iterdir())
    with pytest.raises(StoreNotFound):
        ProjectStore.open(path, readonly=readonly)
    assert tuple(tmp_path.iterdir()) == before


@pytest.mark.parametrize("kind", ["empty", "text", "foreign_sqlite"])
@pytest.mark.parametrize("readonly", [True, False])
def test_open_refuses_foreign_empty_or_corrupt_database_without_adopting_it(tmp_path, kind, readonly):
    path = tmp_path / "foreign.sqlite"
    if kind == "foreign_sqlite":
        alter(path, "CREATE TABLE unrelated (value TEXT)")
    else:
        path.write_bytes(b"" if kind == "empty" else b"not a SQLite database")
    before = path.read_bytes()
    with pytest.raises(StoreCorrupt):
        ProjectStore.open(path, readonly=readonly)
    assert path.read_bytes() == before
    with pytest.raises(StoreExists):
        ProjectStore.create(path, root())
    assert path.read_bytes() == before


def test_creation_does_not_overwrite_valid_store_or_existing_directory(tmp_path):
    path = tmp_path / "db"
    store = ProjectStore.create(path, root())
    before = path.read_bytes()
    with pytest.raises(StoreExists):
        ProjectStore.create(path, root(project_id="other"))
    assert path.read_bytes() == before
    assert store.head().project_id == "project"
    with pytest.raises(StoreExists):
        ProjectStore.create(tmp_path, root())


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_missing_database_with_existing_recovery_artifact_is_not_a_fresh_path(tmp_path, suffix):
    path = tmp_path / "db"
    sidecar = tmp_path / ("db" + suffix)
    sidecar.write_bytes(b"previous database recovery evidence")
    before = sidecar.read_bytes()
    with pytest.raises(StoreExists, match="recovery artifact"):
        ProjectStore.create(path, root())
    assert not path.exists() and sidecar.read_bytes() == before


def test_new_store_cannot_claim_a_root_with_missing_parent(tmp_path):
    path = tmp_path / "db"
    with pytest.raises(StoreConflict, match="parent"):
        ProjectStore.create(path, changed(root()))
    assert not path.exists()


def test_readonly_handle_cannot_commit_and_read_does_not_modify_files(tmp_path):
    path = tmp_path / "db"
    first = root()
    ProjectStore.create(path, first)
    before = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
    store = ProjectStore.open(path)
    store.head()
    store.get(first.revision_id)
    store.history()
    with pytest.raises(StoreReadOnly):
        store.commit(changed(first), expected_revision=first.revision_id)
    assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before


def test_stale_writer_leaves_no_orphan_snapshot_or_head_rewind(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first)
    winner, loser = changed(first, "winner"), changed(first, "loser")
    store.commit(winner, expected_revision=first.revision_id)
    with pytest.raises(StoreConflict, match="stale"):
        store.commit(loser, expected_revision=first.revision_id)
    assert store.head().revision_id == winner.revision_id
    assert raw_count(store.path) == 2
    with pytest.raises(StoreNotFound):
        store.get(loser.revision_id)


def test_exact_redelivery_does_not_add_history_or_rewind_a_later_head(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first)
    second, third = changed(first, "second"), None
    first_result = store.commit(second, expected_revision=first.revision_id)
    assert first_result.inserted
    assert not store.commit(second, expected_revision=first.revision_id).inserted
    third = changed(second, "third")
    store.commit(third, expected_revision=second.revision_id)
    result = store.commit(second, expected_revision=first.revision_id)
    assert result.inserted is False
    assert result.revision_id == second.revision_id
    assert result.head_revision == third.revision_id
    root_retry = store.commit(first, expected_revision=None)
    assert not root_retry.inserted and root_retry.head_revision == third.revision_id
    assert raw_count(store.path) == 3
    with pytest.raises(StoreConflict, match="snapshot's parent"):
        store.commit(second, expected_revision=third.revision_id)


def test_wrong_parent_missing_parent_cross_project_and_new_root_are_refused(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first)
    child = changed(first)
    with pytest.raises(StoreConflict, match="snapshot's parent"):
        store.commit(child, expected_revision="0" * 64)
    missing = ProjectRevision(first.project_id, first.modules, first.instances,
                               parent_revision="0" * 64)
    with pytest.raises(StoreConflict, match="missing parent"):
        store.commit(missing, expected_revision="0" * 64)
    foreign = ProjectRevision("other", first.modules, first.instances,
                               parent_revision=first.revision_id)
    with pytest.raises(StoreConflict, match="another project"):
        store.commit(foreign, expected_revision=first.revision_id)
    with pytest.raises(StoreConflict, match="new root"):
        store.commit(root(intent="another root"), expected_revision=None)
    assert raw_count(store.path) == 1


def test_semantically_invalid_draft_and_inert_source_are_stored_without_execution(tmp_path):
    marker = tmp_path / "not-executed"
    recipe = RecipePin(f"open({str(marker)!r}, 'w').write('bad')", "a" * 64)
    first = ProjectRevision(
        "draft", (ModuleDefinition("m", "sealed_evaluation", recipe),),
        (ModuleInstance("i", "m", {"draft": {"op": "unknown_operation"}}),))
    store = ProjectStore.create(tmp_path / "db", first)
    second = changed(first)
    store.commit(second, expected_revision=first.revision_id)
    assert ProjectStore.open(store.path).head().dumps() == second.dumps()
    assert len(store.history()) == 2 and not marker.exists()


@pytest.mark.parametrize("sql,params", [
    ("PRAGMA application_id=0", ()),
    ("PRAGMA user_version=99", ()),
    ("UPDATE project_store SET schema_version='future'", ()),
    ("CREATE TABLE foreign_table (x TEXT)", ()),
    ("CREATE TABLE sqliteXunexpected (x TEXT)", ()),
    ("CREATE TRIGGER extra AFTER INSERT ON revisions BEGIN SELECT 1; END", ()),
    ("CREATE TRIGGER sqliteXtrigger AFTER INSERT ON revisions BEGIN SELECT 1; END", ()),
    ("UPDATE project_store SET store_id='bad'", ()),
])
def test_unknown_or_changed_schema_fails_closed(tmp_path, sql, params):
    path = tmp_path / "db"
    ProjectStore.create(path, root())
    alter(path, sql, params)
    before = path.read_bytes()
    with pytest.raises(StoreCorrupt):
        ProjectStore.open(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("sql,params", [
    ("UPDATE revisions SET payload='{}'", ()),
    ("UPDATE revisions SET project_id='other'", ()),
    ("UPDATE revisions SET revision_id=?", ("a" * 64,)),
    ("UPDATE project_store SET project_id='other'", ()),
    ("UPDATE project_store SET head_revision=?", ("a" * 64,)),
])
def test_requested_head_must_match_real_payload_and_database_identity(tmp_path, sql, params):
    path = tmp_path / "db"
    store = ProjectStore.create(path, root())
    alter(path, sql, params)
    with pytest.raises(StoreCorrupt):
        store.head()


def test_missing_parent_and_rewound_head_are_not_silently_accepted(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first)
    second = changed(first)
    store.commit(second, expected_revision=first.revision_id)
    alter(store.path, "UPDATE project_store SET head_revision=?", (first.revision_id,))
    with pytest.raises(StoreCorrupt, match="last committed"):
        store.head()
    alter(store.path, "UPDATE project_store SET head_revision=?", (second.revision_id,))
    alter(store.path, "DELETE FROM revisions WHERE revision_id=?", (first.revision_id,))
    with pytest.raises(StoreCorrupt, match="immediate parent"):
        store.head()


def test_unaddressed_old_payload_is_not_scanned_by_head_but_history_and_get_refuse(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first)
    second = changed(first)
    store.commit(second, expected_revision=first.revision_id)
    alter(store.path, "UPDATE revisions SET payload='{}' WHERE revision_id=?",
          (first.revision_id,))
    # The hot-path contract checks its addressed payload, not all past data.
    assert ProjectStore.open(store.path).head().revision_id == second.revision_id
    with pytest.raises(StoreCorrupt, match="payload"):
        store.get(first.revision_id)
    with pytest.raises(StoreCorrupt, match="payload"):
        store.history()
    with pytest.raises(StoreCorrupt, match="payload"):
        store.commit(first, expected_revision=None)


def _spy_on_payload_reads(monkeypatch):
    original = ProjectRevision.loads.__func__
    read_ids = []

    def spy(cls, payload):
        result = original(cls, payload)
        read_ids.append(result.revision_id)
        return result

    monkeypatch.setattr(ProjectRevision, "loads", classmethod(spy))
    return read_ids


def _store_with_history(path, length):
    store = ProjectStore.create(path, root())
    for index in range(length):
        base = store.head()
        store.commit(changed(base, f"rev-{index}"), expected_revision=base.revision_id)
    return store


def test_hot_path_payload_validation_is_constant_in_history_length(tmp_path, monkeypatch):
    """🔴 WHAT THIS PIN USED TO MEASURE AND WHY IT CHANGED (07.09.2026).

    The name promises constancy ACROSS THE LENGTH OF THE HISTORY, but the
    body held ONE history of 13 revisions and checked the list
    `[candidate, head]` — meaning it never varied the length at all, and
    at the same time pinned down that the head gets re-parsed on EVERY
    transaction. The second part became the cost: a measurement of 205
    bodies showed 207 parses of the same head, 38.2 s out of a 57.8 s
    profile. `ProjectStore` now carries a guarantee of ONE handle by THE
    ROW'S BYTES (`_decode_row`), and the pin has been rewritten to what
    its name promises, plus three conditions the guarantee must hold
    under: a fresh handle pays for the head, a warm one does not, and a
    substituted head refuses by name even on a warm one.
    """
    read_ids = _spy_on_payload_reads(monkeypatch)
    counts = {}
    for length in (13, 60):
        store = _store_with_history(tmp_path / f"db-{length}", length)
        # THE MEASUREMENT runs on a FRESH handle: `create`/`commit` above
        # have already warmed theirs, and the pin's subject is the cost
        # of ONE hot operation, not the warming history.
        fresh = ProjectStore.open(tmp_path / f"db-{length}", readonly=False)
        head = fresh.head()
        read_ids.clear()
        next_revision = changed(head, "next")
        fresh.commit(next_revision, expected_revision=head.revision_id)
        counts[length] = len(read_ids)
    # (a) THE NUMBER OF PARSES DOES NOT GROW WITH THE LENGTH OF THE
    # HISTORY. 13 versus 60 revisions — a fivefold difference, and the
    # cost of a commit must stay the same.
    assert counts[13] == counts[60], counts
    assert counts[13] <= 2, counts


def test_a_fresh_handle_pays_for_the_head_before_writing_over_it(tmp_path, monkeypatch):
    """(b) The head is checked at least once on a handle BEFORE writing over it."""
    path = tmp_path / "db"
    _store_with_history(path, 3)
    # The head is read by a DIFFERENT handle: ask `fresh` for it, and it
    # would warm itself, and the pin would end up measuring the warm case
    # under the name of the fresh one.
    head = ProjectStore.open(path).head()
    fresh = ProjectStore.open(path, readonly=False)
    read_ids = _spy_on_payload_reads(monkeypatch)
    next_revision = changed(head, "next")
    read_ids.clear()
    fresh.commit(next_revision, expected_revision=head.revision_id)
    assert read_ids == [next_revision.revision_id, head.revision_id], read_ids


def test_a_warm_handle_does_not_re_parse_the_head_it_already_checked(tmp_path, monkeypatch):
    """(c) A warm handle pays only for the CANDIDATE: the head's bytes are the same."""
    path = tmp_path / "db"
    store = _store_with_history(path, 3)
    head = store.head()
    read_ids = _spy_on_payload_reads(monkeypatch)
    next_revision = changed(head, "next")
    read_ids.clear()
    store.commit(next_revision, expected_revision=head.revision_id)
    assert read_ids == [next_revision.revision_id], read_ids


def test_a_byte_swapped_head_is_refused_even_on_a_warm_handle(tmp_path):
    """(d) The guarantee checks the row's BYTES: a substituted head is a refusal, not a commit."""
    import sqlite3

    path = tmp_path / "db"
    store = _store_with_history(path, 3)
    head = store.head()
    connection = sqlite3.connect(path)
    try:
        payload = connection.execute(
            "SELECT payload FROM revisions WHERE revision_id=?",
            (head.revision_id,)).fetchone()[0]
        connection.execute("UPDATE revisions SET payload=? WHERE revision_id=?",
                           (payload + " ", head.revision_id))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(StoreCorrupt, match="payload"):
        store.commit(changed(head, "next"), expected_revision=head.revision_id)
    with pytest.raises(StoreCorrupt, match="payload"):
        store.head()


@pytest.mark.parametrize("filename", ["space project.sqlite", "question?mode=ro.sqlite",
                                       "fragment#part.sqlite", "проект.sqlite", ":memory:"])
def test_paths_are_quoted_as_paths_not_injected_sqlite_uri_options(tmp_path, filename):
    path = tmp_path / filename
    store = ProjectStore.create(path, root())
    child = changed(store.head())
    store.commit(child, expected_revision=child.parent_revision)
    assert path.is_file()
    assert ProjectStore.open(path).head().revision_id == child.revision_id
    assert set(item.name for item in tmp_path.iterdir()) == {filename}


def test_handle_refuses_a_different_store_replaced_at_the_same_path(tmp_path):
    first_path, other_path = tmp_path / "first", tmp_path / "other"
    handle = ProjectStore.create(first_path, root())
    ProjectStore.create(other_path, root())  # even the same logical project/root
    os.replace(other_path, first_path)
    with pytest.raises(StoreCorrupt, match="identity changed"):
        handle.head()


@pytest.mark.parametrize("timeout", [-1, 31, 10 ** 1000, float("nan"), float("inf"), True, "5"])
def test_invalid_timeout_does_not_create_files(tmp_path, timeout):
    path = tmp_path / "db"
    with pytest.raises(ProjectStoreError, match="timeout"):
        ProjectStore.create(path, root(), timeout=timeout)
    assert not path.exists()


def test_unknown_lookup_and_invalid_readonly_do_not_mutate_store(tmp_path):
    store = ProjectStore.create(tmp_path / "db", root())
    with pytest.raises(StoreNotFound):
        store.get("f" * 64)
    with pytest.raises(StoreNotFound):
        store.get(True)
    with pytest.raises(ProjectStoreError, match="readonly"):
        ProjectStore.open(store.path, readonly="false")


def test_nul_in_path_is_a_named_boundary_error():
    with pytest.raises(ProjectStoreError, match="NUL"):
        ProjectStore.open("invalid\x00path")


def test_invalid_python_candidate_cannot_poison_persisted_history(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first)
    second = changed(first)
    object.__setattr__(second, "intent", "content changed without updating its hash")
    with pytest.raises(ProjectStoreError, match="candidate revision payload"):
        store.commit(second, expected_revision=first.revision_id)
    assert store.head().revision_id == first.revision_id and raw_count(store.path) == 1
    invalid_root = root()
    object.__setattr__(invalid_root, "intent", "also tampered")
    path = tmp_path / "new"
    with pytest.raises(ProjectStoreError, match="candidate revision payload"):
        ProjectStore.create(path, invalid_root)
    assert not path.exists()


class _Proxy:
    def __init__(self, connection, phase):
        self.connection, self.phase = connection, phase

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args):
        if self.phase == "before_commit" and sql == "COMMIT":
            raise sqlite3.OperationalError("injected commit failure")
        result = self.connection.execute(sql, *args)
        if ((self.phase == "after_insert" and sql.startswith("INSERT INTO revisions"))
                or (self.phase == "after_update" and sql.startswith("UPDATE project_store"))
                or (self.phase == "after_commit" and sql == "COMMIT")):
            raise sqlite3.OperationalError("injected failure")
        return result


def _inject(monkeypatch, phase):
    import kir.project_store as module

    original = module._connect
    monkeypatch.setattr(module, "_connect", lambda *args, **kwargs:
                        _Proxy(original(*args, **kwargs), phase))


@pytest.mark.parametrize("phase", ["after_insert", "after_update", "before_commit"])
def test_write_or_commit_failure_rolls_back_snapshot_and_head(tmp_path, monkeypatch, phase):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first)
    second = changed(first)
    with monkeypatch.context() as patch:
        _inject(patch, phase)
        with pytest.raises(ProjectStoreError):
            store.commit(second, expected_revision=first.revision_id)
    assert store.head().revision_id == first.revision_id
    assert raw_count(store.path) == 1
    with pytest.raises(StoreNotFound):
        store.get(second.revision_id)
    assert store.commit(second, expected_revision=first.revision_id).inserted


def test_failed_ack_after_commit_is_unknown_and_retry_is_not_an_extra_commit(tmp_path, monkeypatch):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first)
    second = changed(first)
    with monkeypatch.context() as patch:
        _inject(patch, "after_commit")
        with pytest.raises(StoreCommitUnknown):
            store.commit(second, expected_revision=first.revision_id)
    assert store.head().revision_id == second.revision_id
    result = store.commit(second, expected_revision=first.revision_id)
    assert not result.inserted and raw_count(store.path) == 2


def test_failed_creation_retains_fail_closed_file_and_never_adopts_it(tmp_path, monkeypatch):
    path = tmp_path / "db"
    with monkeypatch.context() as patch:
        _inject(patch, "after_insert")
        with pytest.raises(ProjectStoreError):
            ProjectStore.create(path, root())
    assert path.exists()
    with pytest.raises(StoreCorrupt):
        ProjectStore.open(path)
    with pytest.raises(StoreExists):
        ProjectStore.create(path, root())


def test_busy_writer_refuses_without_leaking_snapshot(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first, timeout=0.01)
    connection = sqlite3.connect(store.path, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(StoreBusy):
            store.commit(changed(first), expected_revision=first.revision_id)
    finally:
        connection.close()
    assert raw_count(store.path) == 1


def test_commit_busy_due_to_reader_rolls_back_its_insert(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first, timeout=0.01)
    reader = sqlite3.connect(store.path, isolation_level=None)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM project_store").fetchall()
        with pytest.raises(StoreBusy):
            store.commit(changed(first), expected_revision=first.revision_id)
    finally:
        reader.close()
    assert store.head().revision_id == first.revision_id and raw_count(store.path) == 1


def _writer(path, payload, start, result):
    try:
        proposal = ProjectRevision.loads(payload)
        store = ProjectStore.open(path, readonly=False)
        result.put(("ready", os.getpid()))
        if not start.wait(10):
            raise RuntimeError("writer barrier timed out")
        receipt = store.commit(proposal, expected_revision=proposal.parent_revision)
        result.put(("committed", receipt.inserted, receipt.revision_id, receipt.head_revision))
    except Exception as exc:
        result.put((type(exc).__name__, str(exc)))


@pytest.mark.parametrize("same_proposal", [False, True])
def test_real_process_writers_cas_or_acknowledge_exact_redelivery(tmp_path, same_proposal):
    first = root()
    store = ProjectStore.create(tmp_path / "db", first)
    left = changed(first, "left")
    right = left if same_proposal else changed(first, "right")
    context = multiprocessing.get_context("spawn")
    start, result = context.Event(), context.Queue()
    processes = [context.Process(target=_writer, args=(str(store.path), proposal.dumps(), start, result))
                 for proposal in (left, right)]
    try:
        for process in processes:
            process.start()
        ready = [result.get(timeout=15), result.get(timeout=15)]
        assert all(item[0] == "ready" for item in ready), ready
        assert len({item[1] for item in ready}) == 2
        start.set()
        outcomes = [result.get(timeout=15), result.get(timeout=15)]
        for process in processes:
            process.join(15)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        result.close()
    if same_proposal:
        assert all(item[0] == "committed" for item in outcomes), outcomes
        assert sorted(item[1] for item in outcomes) == [False, True]
    else:
        assert sorted(item[0] for item in outcomes) == ["StoreConflict", "committed"], outcomes
    history = store.history()
    assert len(history) == 2 and raw_count(store.path) == 2
    assert history[-1].revision_id in (left.revision_id, right.revision_id)


class _CrashProxy:
    def __init__(self, connection, phase):
        self.connection, self.phase = connection, phase
        connection.execute("PRAGMA cache_size=1")
        connection.execute("PRAGMA cache_spill=ON")

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args):
        result = self.connection.execute(sql, *args)
        if self.phase == "after_insert" and sql.startswith("INSERT INTO revisions"):
            os._exit(71)
        if self.phase == "after_commit" and sql == "COMMIT":
            os._exit(72)
        return result


def _crash_writer(path, payload, phase):
    import kir.project_store as module

    original = module._connect
    module._connect = lambda *args, **kwargs: _CrashProxy(original(*args, **kwargs), phase)
    store = ProjectStore.open(path, readonly=False)
    proposal = ProjectRevision.loads(payload)
    store.commit(proposal, expected_revision=proposal.parent_revision)
    os._exit(99)  # named crash point was not reached; test must fail


def _crash_foreign_database(path):
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("CREATE TABLE external_data (payload TEXT)")
    connection.execute("PRAGMA cache_size=1")
    connection.execute("PRAGMA cache_spill=ON")
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("INSERT INTO external_data VALUES (?)", ("x" * 250000,))
    os._exit(73)


def test_writable_open_does_not_recover_a_foreign_hot_database(tmp_path):
    path = tmp_path / "foreign"
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_crash_foreign_database, args=(str(path),))
    process.start()
    process.join(20)
    if process.is_alive():
        process.terminate()
        process.join(5)
    assert process.exitcode == 73
    journal = tmp_path / "foreign-journal"
    assert journal.stat().st_size > 512
    before = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
    with pytest.raises(StoreCorrupt, match="header"):
        ProjectStore.open(path, readonly=False)
    assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before


@pytest.mark.parametrize("phase,exitcode", [("after_insert", 71), ("after_commit", 72)])
def test_actual_process_crash_preserves_atomic_history_and_retry_identity(tmp_path, phase, exitcode):
    first = root()
    path = tmp_path / "db"
    ProjectStore.create(path, first)
    second = changed(first, metadata={"large_evaluation": "x" * 250000})
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_crash_writer, args=(str(path), second.dumps(), phase))
    process.start()
    process.join(20)
    if process.is_alive():
        process.terminate()
        process.join(5)
    assert process.exitcode == exitcode
    if phase == "after_insert":
        # Forced page-cache spill creates a real hot rollback journal. A read
        # command must refuse, not silently acquire write permission to recover.
        before = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
        with pytest.raises(StoreRecoveryRequired):
            ProjectStore.open(path)
        assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before
        recovered = ProjectStore.open(path, readonly=False)
        assert recovered.head().revision_id == first.revision_id
        assert len(recovered.history()) == 1
        assert recovered.commit(second, expected_revision=first.revision_id).inserted
    else:
        assert ProjectStore.open(path).head().revision_id == second.revision_id
        recovered = ProjectStore.open(path, readonly=False)
        assert not recovered.commit(second, expected_revision=first.revision_id).inserted
    assert len(ProjectStore.open(path).history()) == 2
