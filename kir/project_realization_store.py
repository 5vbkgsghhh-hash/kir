"""Inert Level realization records inside ProjectStore's SQLite transaction.

This module never opens a connection, sends a request, recreates a fresh plan or
observation, or grants replay. ProjectStore alone owns BEGIN/COMMIT/rollback.
Streams are scoped to an original publication, not whole-building realization.
"""
from dataclasses import dataclass, field, replace
import json
import sqlite3

from kir.project import _canonical, _hash
from kir.project_store import (REALIZATION_STORE_SCHEMA, RESOLUTION_STORE_SCHEMA, ProjectStoreError, StoreConflict,
    StoreCorrupt, StoreNotFound, StoreUpgradeRequired, _find_revision, _HEX64,
    _REALIZATION_SCHEMAS, _RESOLUTION_SCHEMAS)
from kir.saved_execution import SavedExecutionRecord, SavedExecutionError, UPDATE_ARCHIVE_SCHEMA, MAX_RECORD_BYTES


REALIZATION_TABLES = {
    "level_streams": """CREATE TABLE level_streams (
        stream_id TEXT NOT NULL PRIMARY KEY CHECK (length(stream_id) = 64),
        original_payload TEXT NOT NULL,
        checkpoint_digest TEXT REFERENCES level_settlements(digest),
        pending_archive_digest TEXT REFERENCES level_update_archives(digest)
    )""",
    "level_update_archives": """CREATE TABLE level_update_archives (
        digest TEXT NOT NULL PRIMARY KEY CHECK (length(digest) = 64),
        stream_id TEXT NOT NULL REFERENCES level_streams(stream_id),
        expected_checkpoint TEXT REFERENCES level_settlements(digest),
        base_revision TEXT NOT NULL REFERENCES revisions(revision_id),
        proposed_revision TEXT NOT NULL REFERENCES revisions(revision_id),
        journal_id TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE (journal_id, operation_id),
        UNIQUE (stream_id, expected_checkpoint)
    )""",
    "level_settlements": """CREATE TABLE level_settlements (
        digest TEXT NOT NULL PRIMARY KEY CHECK (length(digest) = 64),
        stream_id TEXT NOT NULL REFERENCES level_streams(stream_id),
        archive_digest TEXT NOT NULL UNIQUE REFERENCES level_update_archives(digest),
        parent_checkpoint TEXT REFERENCES level_settlements(digest),
        sequence INTEGER NOT NULL CHECK (sequence >= 0),
        base_revision TEXT NOT NULL REFERENCES revisions(revision_id),
        proposed_revision TEXT NOT NULL REFERENCES revisions(revision_id),
        payload TEXT NOT NULL,
        UNIQUE (stream_id, sequence)
    )""",
    "level_scope_owners": """CREATE TABLE level_scope_owners (
        journal_id TEXT NOT NULL,
        instance_id TEXT NOT NULL,
        revit_version TEXT NOT NULL,
        document_key TEXT NOT NULL,
        unique_id TEXT NOT NULL,
        stream_id TEXT NOT NULL REFERENCES level_streams(stream_id),
        PRIMARY KEY (journal_id, instance_id, revit_version, document_key, unique_id)
    )""",
}
_ARCHIVE_ROW = "digest, stream_id, expected_checkpoint, base_revision, proposed_revision, journal_id, operation_id, payload"
_SETTLEMENT_ROW = "digest, stream_id, archive_digest, parent_checkpoint, sequence, base_revision, proposed_revision, payload"
_RESOLUTION_ROW = "digest, archive_digest, stream_id, expected_checkpoint, payload"
# /3 is immutable. /4's ordinary index permits another explicitly prepared
# attempt at the SAME accepted checkpoint, but never reuse of a native UUID.
_ARCHIVES_V4_SQL = REALIZATION_TABLES["level_update_archives"].replace(
    "CREATE TABLE level_update_archives", 'CREATE TABLE "level_update_archives"').replace(
    ",\n        UNIQUE (stream_id, expected_checkpoint)", "")
_RESOLUTIONS_SQL = """CREATE TABLE level_resolutions (
    digest TEXT NOT NULL PRIMARY KEY CHECK (length(digest) = 64),
    archive_digest TEXT NOT NULL UNIQUE REFERENCES level_update_archives(digest),
    stream_id TEXT NOT NULL REFERENCES level_streams(stream_id),
    expected_checkpoint TEXT REFERENCES level_settlements(digest),
    payload TEXT NOT NULL
)"""
RESOLUTION_INDEXES = {"level_archive_checkpoint":
    "CREATE INDEX level_archive_checkpoint ON level_update_archives(stream_id, expected_checkpoint)",
    "level_resolution_checkpoint":
    "CREATE INDEX level_resolution_checkpoint ON level_resolutions(stream_id, expected_checkpoint)"}


def realization_tables(schema):
    if schema == REALIZATION_STORE_SCHEMA:
        return dict(REALIZATION_TABLES)
    if schema in _RESOLUTION_SCHEMAS:
        return {**REALIZATION_TABLES, "level_update_archives": _ARCHIVES_V4_SQL, "level_resolutions": _RESOLUTIONS_SQL}
    raise StoreUpgradeRequired("unsupported Level ledger schema")


def migrate_resolution_schema(connection):
    """Called ONLY inside ProjectStore's FK-off explicit migration transaction."""
    _require(connection.in_transaction and connection.execute("PRAGMA foreign_keys").fetchone() == (0,),
             "Level migration requires its explicit FK-off transaction")
    connection.execute(_ARCHIVES_V4_SQL.replace('"level_update_archives"', '"level_update_archives_next"', 1))
    connection.execute(f"INSERT INTO level_update_archives_next ({_ARCHIVE_ROW}) SELECT {_ARCHIVE_ROW} FROM level_update_archives")
    counts = connection.execute("SELECT (SELECT count(*) FROM level_update_archives), (SELECT count(*) FROM level_update_archives_next)").fetchone()
    _require(counts[0] == counts[1], "Level migration row count differs", stored=True)
    # Compare within SQLite; do not deserialize whole history into Python.
    for left, right in (("level_update_archives", "level_update_archives_next"),
                        ("level_update_archives_next", "level_update_archives")):
        mismatch = connection.execute(f"SELECT 1 FROM (SELECT {_ARCHIVE_ROW} FROM {left} EXCEPT SELECT {_ARCHIVE_ROW} FROM {right}) LIMIT 1").fetchone()
        _require(mismatch is None, "Level migration changed archived bytes or identities", stored=True)
    connection.execute("DROP TABLE level_update_archives")
    connection.execute('ALTER TABLE level_update_archives_next RENAME TO "level_update_archives"')
    connection.execute(_RESOLUTIONS_SQL)
    for sql in RESOLUTION_INDEXES.values():
        connection.execute(sql)


@dataclass(frozen=True, slots=True)
class LevelReservationResult:
    stream_id: str
    archive_digest: str
    checkpoint_digest: str | None
    pending_archive_digest: str | None
    inserted: bool
    may_retry: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class LevelSettlementResult:
    stream_id: str
    settlement_digest: str
    checkpoint_digest: str
    pending_archive_digest: str | None
    inserted: bool
    may_retry: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class LevelResolutionResult:
    stream_id: str
    resolution_digest: str
    checkpoint_digest: str | None
    pending_archive_digest: str | None
    inserted: bool
    may_retry: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class RecordedLevelBaseline:
    """Detached retained claims. Construction never grants fresh authority."""
    store_id: str
    project_id: str
    stream_id: str
    checkpoint_digest: str | None
    pending_archive_digest: str | None
    _original_json: str = field(repr=False)
    _accepted_json: str | None = field(repr=False)

    @property
    def original(self):
        return json.loads(self._original_json)

    @property
    def accepted(self):
        return None if self._accepted_json is None else json.loads(self._accepted_json)

    @property
    def baseline_revision(self):
        return (self.original["project"]["revision_id"] if self._accepted_json is None
                else self.accepted["proposed_revision"])

    def to_dict(self):
        return {"schema": "kir-recorded-level-baseline/1", "stream_id": self.stream_id,
            "store_id": self.store_id, "project_id": self.project_id,
            "original": self.original, "accepted": self.accepted,
            "checkpoint_digest": self.checkpoint_digest, "pending_archive_digest": self.pending_archive_digest,
            "baseline_revision": self.baseline_revision,
            "claims": {"evidence": "retained_claims_not_fresh_observation", "scope": "selected_level_stream",
                       "geometry": "not_established", "engineering": "not_established", "retry_permission": "none"}}


@dataclass(frozen=True, slots=True)
class _Archive:
    record: SavedExecutionRecord
    payload: str
    original_payload: str
    stream_id: str
    project_id: str
    base: str
    proposed: str


def _require(value, message, *, stored=False):
    if not value:
        raise (StoreCorrupt if stored else StoreConflict)(message)


def _digest(value, *, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ProjectStoreError("expected a lowercase SHA-256 identity")


def _schema(state):
    if state.schema not in _REALIZATION_SCHEMAS:
        raise StoreUpgradeRequired("Level streams require explicit kir-project-store/3 upgrade")


def _resolution_schema(state):
    if state.schema not in _RESOLUTION_SCHEMAS:
        raise StoreUpgradeRequired("Level not_started resolution requires explicit kir-project-store/4 upgrade")


def _json_payload(payload, budget=MAX_RECORD_BYTES):
    from kir.connector_result import _json
    try:
        if type(payload) is not str:
            raise ValueError("payload is not text")
        value, _ = _json(payload, budget)
        if _canonical(value) != payload:
            raise ValueError("payload is not canonical")
        return value
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise StoreCorrupt("stored Level payload is not canonical bounded JSON") from error


def _ledger_row(connection, sql, args, *, budget):
    """Bound SQLite row materialization before Python receives stored TEXT.

    Scope the limit to this ledger query, then restore it: authored snapshots
    and geometry assets have their own contracts and may legitimately be larger.
    Small fixed slack covers the indexed digest/sequence fields in the same row.
    """
    previous = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(previous, budget + 4096))
    try:
        return connection.execute(sql, args).fetchone()
    except sqlite3.DataError as error:
        if (getattr(error, "sqlite_errorcode", 0) & 0xFF) == sqlite3.SQLITE_TOOBIG:
            raise StoreCorrupt("stored Level ledger row exceeds its SQLite byte budget") from error
        raise
    finally:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, previous)


def checked_archive(record) -> _Archive:
    """Use the existing exact archive codec; no recompile or recipe execution."""
    if type(record) is not SavedExecutionRecord:
        raise ProjectStoreError("reservation requires exact SavedExecutionRecord")
    try:
        decoded = SavedExecutionRecord._from_bytes(record._raw)
        if decoded.digest != record.digest:
            raise ValueError("archive identity differs")
        data = decoded.to_dict()
        if data["schema"] != UPDATE_ARCHIVE_SCHEMA:
            raise ValueError("update archive required")
        submitted = data["update_submission"]
        original, update = submitted["original_publication"], submitted["update"]
        return _Archive(decoded, decoded._raw.decode("utf-8"), _canonical(original), original["binding_digest"],
                        original["project"]["project_id"], update["base_revision"], update["proposed_revision"])
    except (SavedExecutionError, TypeError, ValueError, KeyError) as error:
        raise ProjectStoreError("invalid checked Level update archive") from error


def checked_settlement(qualified):
    from kir.level_settlement import QualifiedLevelSettlement, validate_level_settlement_claims
    if type(qualified) is not QualifiedLevelSettlement:
        raise ProjectStoreError("settlement requires exact QualifiedLevelSettlement, not saved claims")
    archive = checked_archive(qualified.record)
    try:
        payload = _canonical(qualified.to_dict())
        data = _json_payload(payload)
        validate_level_settlement_claims(data, archive.record)
        if data["settlement_digest"] != qualified.digest:
            raise ValueError("settlement identity differs")
    except (TypeError, ValueError, KeyError) as error:
        raise ProjectStoreError("invalid qualified Level settlement payload") from error
    return archive, data, payload


def checked_resolution(qualified):
    from kir.level_resolution import QualifiedLevelNotStarted, validate_level_not_started_claims
    if type(qualified) is not QualifiedLevelNotStarted:
        raise ProjectStoreError("resolution requires exact QualifiedLevelNotStarted, not saved claims")
    archive = checked_archive(qualified.record)
    try:
        payload = _canonical(qualified.to_dict())
        data = _json_payload(payload)
        validate_level_not_started_claims(data, archive.record)
        if data["resolution_digest"] != qualified.digest:
            raise ValueError("resolution identity differs")
    except (TypeError, ValueError, KeyError) as error:
        raise ProjectStoreError("invalid qualified Level not_started payload") from error
    return archive, data, payload


def _scope(original):
    execution = original["execution"]
    target = execution["target"]
    prefix = (target["journal_id"], target["instance_id"], target["revit_version"], execution["precondition"]["document_key"])
    return {(*prefix, row["element_identity"]["unique_id"]) for row in original["outputs"]}


def _baseline_reference(state, archive, expected_checkpoint, *, stored=False):
    submitted = archive.record.update_submission
    reference = submitted.get("baseline_ref")
    if submitted["schema"] == "kir-submitted-level-update/1":
        _require(reference is None and expected_checkpoint is None,
                 "initial Level archive cannot claim an accepted checkpoint", stored=stored)
    elif submitted["schema"] == "kir-submitted-level-update/2":
        _require(type(reference) is dict and expected_checkpoint is not None
                 and reference == {"store_id": state.store_id, "stream_id": archive.stream_id,
                    "checkpoint_digest": expected_checkpoint, "base_revision": archive.base},
                 "iterative Level archive checkpoint owner differs", stored=stored)
    else:
        _require(False, "unsupported Level submission profile", stored=stored)


def _check_before_checkpoint(archive, accepted, *, stored=False):
    """Independent owner check against SQL evidence, not the caller's DTO.

    An imported RecordedLevelBaseline may have been edited. It cannot replace
    the actual accepted after-read under this transaction. Fields use the same
    pure projection as acceptance; VersionGuid is not a geometry oracle.
    """
    from kir.level_update_acceptance import _fields
    before = archive.record.update_submission["before_observation"]
    try:
        after = accepted["after"]
        _require(_canonical(before["target"]) == _canonical(after["target"])
                 and before["precondition"]["document_key"] == after["precondition"]["document_key"]
                 and before["precondition"]["revision"] >= after["precondition"]["revision"],
                 "Level before-observation predates or differs from accepted native checkpoint", stored=stored)
        _require(set(before["rows"]) == set(after["rows"]), "Level before-observation scope differs from checkpoint", stored=stored)
        _require(all(_fields(row) is not None and _canonical(_fields(row)) == _canonical(_fields(after["rows"][uid]))
                     for uid, row in before["rows"].items()),
                 "Level before-observation fields differ from actual accepted checkpoint", stored=stored)
    except (TypeError, KeyError, ValueError) as error:
        raise (StoreCorrupt if stored else StoreConflict)("invalid Level before/checkpoint relation") from error


def _check_projects(connection, state, archive, *, stored=False):
    _require(archive.project_id == state.project_id, "Level stream belongs to another project", stored=stored)
    original = archive.record.update_submission["original_publication"]
    original_project = _find_revision(connection, state, original["project"]["revision_id"])
    base = _find_revision(connection, state, archive.base)
    proposed = _find_revision(connection, state, archive.proposed)
    _require(original_project is not None and base is not None and proposed is not None,
             "Level update references missing authored history", stored=stored)
    _require(proposed.parent_revision == base.revision_id,
             "Level update proposed revision must be a direct child", stored=stored)
    addresses = {(instance.key, output.key): (instance, output, oid)
                 for instance, output, oid in original_project.addressed_outputs()}
    for row in original["outputs"]:
        found = addresses.get((row["instance_key"], row["output_key"]))
        _require(found is not None and found[0].module_key == row["module_key"]
                 and found[2] == row["output_id"] and found[1].operation["op"] == row["source_op"]
                 and _hash(found[1].to_dict()) == row["authored_output_digest"],
                 "original binding differs from stored authored outputs", stored=stored)
    report = archive.record.update_submission["update"]
    before = {oid: (instance, output) for instance, output, oid in base.addressed_outputs()}
    after = {oid: output for _, output, oid in proposed.addressed_outputs()}
    selected = report["target_output_id"]
    _require(selected in before and selected in after, "Level update output is absent", stored=stored)
    instance, old = before[selected]
    new = after[selected]
    module = next(item for item in base.modules if item.key == instance.module_key)
    _require(module.owner == "explicit" and module.recipe is None and old.geometry is None and new.geometry is None
             and old.operation["op"] == new.operation["op"] == "create_level"
             and old.operation.get("elev_mm") == report["old_elev_mm"]
             and new.operation.get("elev_mm") == report["new_elev_mm"],
             "Level update does not match stored explicit elevation values", stored=stored)
    _require(_canonical({**dict(new.operation), "elev_mm": old.operation["elev_mm"]}) == _canonical(dict(old.operation)),
             "Level update changes another output field", stored=stored)
    expected = base.replace_instance(replace(instance, outputs=tuple(new if output.key == old.key else output
        for output in instance.outputs)), expected_revision=base.revision_id)
    _require(expected.dumps() == proposed.dumps(), "Level update includes other authored changes", stored=stored)


def _checkpoint_stub(connection, digest, stream_id):
    """Verify the addressed parent, without recursively scanning all history."""
    from kir.level_settlement import MAX_SETTLEMENT_BYTES
    row = _ledger_row(connection, f"SELECT {_SETTLEMENT_ROW} FROM level_settlements WHERE digest=?",
                      (digest,), budget=MAX_SETTLEMENT_BYTES)
    _require(row is not None and row[1] == stream_id, "missing or foreign Level checkpoint", stored=True)
    data = _json_payload(row[7])
    _require(type(data) is dict and data.get("settlement_digest") == digest
             and _hash({k: v for k, v in data.items() if k != "settlement_digest"}) == digest
             and data.get("original_binding_digest") == stream_id
             and data.get("archive_digest") == row[2]
             and data.get("base_revision") == row[5] and data.get("proposed_revision") == row[6]
             and type(row[4]) is int and row[4] >= 0,
             "Level checkpoint row differs from its payload", stored=True)
    return row, data


def _read_archive(connection, state, digest):
    row = _ledger_row(connection, f"SELECT {_ARCHIVE_ROW} FROM level_update_archives WHERE digest=?",
                      (digest,), budget=MAX_RECORD_BYTES)
    if row is None:
        raise StoreNotFound("Level update archive is not in this store")
    try:
        info = checked_archive(SavedExecutionRecord._from_bytes(row[7].encode("utf-8")))
    except (ProjectStoreError, TypeError, ValueError, AttributeError) as error:
        raise StoreCorrupt("stored Level archive is invalid") from error
    binding = info.record.binding_dict()
    _require(row[:2] == (info.record.digest, info.stream_id) and row[3:7] == (
        info.base, info.proposed, binding["target"]["journal_id"], binding["operation_id"]),
        "Level archive row identity differs", stored=True)
    _baseline_reference(state, info, row[2], stored=True)
    stream = _ledger_row(connection, "SELECT original_payload FROM level_streams WHERE stream_id=?",
                         (info.stream_id,), budget=MAX_RECORD_BYTES)
    _require(stream == (info.original_payload,), "Level archive original stream differs", stored=True)
    original = info.record.update_submission["original_publication"]
    expected_base = original["project"]["revision_id"]
    if row[2] is not None:
        _, parent = _checkpoint_stub(connection, row[2], info.stream_id)
        expected_base = parent["proposed_revision"]
        _check_before_checkpoint(info, parent, stored=True)
    _require(info.base == expected_base, "Level archive base differs from reserved checkpoint", stored=True)
    _check_projects(connection, state, info, stored=True)
    return row, info


def _read_settlement(connection, state, digest):
    row = connection.execute("SELECT stream_id FROM level_settlements WHERE digest=?", (digest,)).fetchone()
    if row is None:
        raise StoreNotFound("Level settlement is not in this store")
    row, data = _checkpoint_stub(connection, digest, row[0])
    try:
        archive_row, archive = _read_archive(connection, state, row[2])
        from kir.level_settlement import validate_level_settlement_claims
        validate_level_settlement_claims(data, archive.record)
    except (StoreNotFound, TypeError, ValueError) as error:
        raise StoreCorrupt("stored Level settlement evidence is inconsistent") from error
    _require(row[1] == archive.stream_id and row[3] == archive_row[2]
             and row[5:7] == (archive.base, archive.proposed), "Level settlement reservation differs", stored=True)
    expected_sequence = 0
    if row[3] is not None:
        parent, _ = _checkpoint_stub(connection, row[3], row[1])
        expected_sequence = parent[4] + 1
    _require(row[4] == expected_sequence, "Level settlement sequence differs from parent", stored=True)
    if state.schema in _RESOLUTION_SCHEMAS:
        _require(connection.execute("SELECT digest FROM level_resolutions WHERE archive_digest=?", (row[2],)).fetchone() is None,
                 "Level archive has conflicting terminal outcomes", stored=True)
    return row, data


def _read_resolution(connection, state, digest):
    from kir.level_resolution import validate_level_not_started_claims, MAX_RESOLUTION_BYTES
    row = _ledger_row(connection, f"SELECT {_RESOLUTION_ROW} FROM level_resolutions WHERE digest=?",
                      (digest,), budget=MAX_RESOLUTION_BYTES)
    if row is None:
        raise StoreNotFound("Level not_started resolution is not in this store")
    data = _json_payload(row[4], MAX_RESOLUTION_BYTES)
    try:
        archive_row, archive = _read_archive(connection, state, row[1])
        validate_level_not_started_claims(data, archive.record)
    except (StoreNotFound, TypeError, ValueError) as error:
        raise StoreCorrupt("stored Level not_started evidence is inconsistent") from error
    _require(row[:4] == (data["resolution_digest"], data["archive_digest"], data["original_binding_digest"], archive_row[2])
             and data["resolution_digest"] == digest and row[2] == archive.stream_id,
             "Level resolution row differs from its exact reserved input", stored=True)
    _require(connection.execute("SELECT digest FROM level_settlements WHERE archive_digest=?", (row[1],)).fetchone() is None,
             "Level archive has conflicting terminal outcomes", stored=True)
    return row, data


def read_baseline(connection, state, stream_id):
    _schema(state)
    _digest(stream_id)
    row = _ledger_row(connection, "SELECT original_payload, checkpoint_digest, pending_archive_digest FROM level_streams WHERE stream_id=?",
                      (stream_id,), budget=MAX_RECORD_BYTES)
    if row is None:
        raise StoreNotFound("Level stream is not in this store")
    original = _json_payload(row[0])
    _require(type(original) is dict and original.get("binding_digest") == stream_id
             and _hash({k: v for k, v in original.items() if k != "binding_digest"}) == stream_id,
             "Level original binding identity differs", stored=True)
    try:
        scope = _scope(original)
    except (TypeError, KeyError) as error:
        raise StoreCorrupt("malformed original Level scope") from error
    stored_scope = set(connection.execute("SELECT journal_id, instance_id, revit_version, document_key, unique_id FROM level_scope_owners WHERE stream_id=? LIMIT ?", (stream_id, len(scope) + 1)))
    _require(scope == stored_scope and bool(scope), "Level scoped UID ownership differs", stored=True)
    if state.schema in _RESOLUTION_SCHEMAS:
        double = connection.execute("""SELECT a.digest FROM level_update_archives AS a
            JOIN level_settlements AS s ON s.archive_digest=a.digest
            JOIN level_resolutions AS r ON r.archive_digest=a.digest WHERE a.stream_id=? LIMIT 1""", (stream_id,)).fetchone()
        _require(double is None, "Level archive has conflicting terminal outcomes", stored=True)
        unresolved = connection.execute("""SELECT a.digest FROM level_update_archives AS a
            LEFT JOIN level_settlements AS s ON s.archive_digest=a.digest AND s.stream_id=a.stream_id AND s.parent_checkpoint IS a.expected_checkpoint
            LEFT JOIN level_resolutions AS r ON r.archive_digest=a.digest AND r.stream_id=a.stream_id AND r.expected_checkpoint IS a.expected_checkpoint
            WHERE a.stream_id=? AND s.digest IS NULL AND r.digest IS NULL LIMIT 2""", (stream_id,)).fetchall()
    else:
        unresolved = connection.execute("""SELECT a.digest FROM level_update_archives AS a
        LEFT JOIN level_settlements AS s ON s.archive_digest=a.digest
        WHERE a.stream_id=? AND s.digest IS NULL LIMIT 2""", (stream_id,)).fetchall()
    _require({item[0] for item in unresolved} == ({row[2]} if row[2] is not None else set()),
             "Level pending pointer differs from unresolved archived operations", stored=True)
    latest = connection.execute("SELECT digest, sequence FROM level_settlements WHERE stream_id=? ORDER BY sequence DESC LIMIT 1", (stream_id,)).fetchone()
    accepted = None
    if row[1] is None:
        _require(latest is None, "Level checkpoint lost its accepted history", stored=True)
    else:
        try:
            checkpoint, accepted = _read_settlement(connection, state, row[1])
        except StoreNotFound as error:
            raise StoreCorrupt("Level stream checkpoint is missing") from error
        _require(latest == (row[1], checkpoint[4]) and checkpoint[1] == stream_id,
                 "Level checkpoint is not the latest settlement", stored=True)
    if row[2] is not None:
        try:
            pending, archive = _read_archive(connection, state, row[2])
        except StoreNotFound as error:
            raise StoreCorrupt("Level stream pending archive is missing") from error
        _require(archive.stream_id == stream_id and pending[2] == row[1]
                 and connection.execute("SELECT digest FROM level_settlements WHERE archive_digest=?", (row[2],)).fetchone() is None,
                 "Level pending reservation differs from stream checkpoint", stored=True)
    # These refusals authorize an empty pending slot at the CURRENT checkpoint;
    # validate their payloads, not just existence of a terminal marker. Historical
    # resolutions at older accepted checkpoints remain part of history() audit.
    resolved_current = False
    if state.schema in _RESOLUTION_SCHEMAS:
        for (digest,) in connection.execute("SELECT digest FROM level_resolutions WHERE stream_id=? AND expected_checkpoint IS ?", (stream_id, row[1])):
            _read_resolution(connection, state, digest)
            resolved_current = True
    _require(accepted is not None or row[2] is not None or resolved_current,
             "empty Level stream has no retained reservation or resolution", stored=True)
    return RecordedLevelBaseline(state.store_id, state.project_id, stream_id, row[1], row[2], row[0],
                                 None if accepted is None else _canonical(accepted))


def reserve(connection, state, archive, expected_checkpoint, *, expected_project_revision=None):
    _schema(state)
    if expected_project_revision is not None:
        _digest(expected_project_revision)
        _require(state.head.revision_id == expected_project_revision,
                 "Level expected authored head changed before reservation")
    from kir.project_create_store import require_native_operation_available
    native_binding = archive.record.binding_dict()
    require_native_operation_available(connection, state,
        native_binding["target"]["journal_id"], native_binding["operation_id"])
    _digest(expected_checkpoint, nullable=True)
    _baseline_reference(state, archive, expected_checkpoint)
    _check_projects(connection, state, archive)
    exists = connection.execute("SELECT stream_id FROM level_streams WHERE stream_id=?", (archive.stream_id,)).fetchone()
    baseline = read_baseline(connection, state, archive.stream_id) if exists else None
    if baseline is not None:
        _require(baseline._original_json == archive.original_payload, "Level stream original binding changed")
    previous = connection.execute("SELECT digest FROM level_update_archives WHERE digest=?", (archive.record.digest,)).fetchone()
    if previous:
        prior, found = _read_archive(connection, state, archive.record.digest)
        _require(found.payload == archive.payload and prior[2] == expected_checkpoint,
                 "Level reservation replay differs from original input/checkpoint")
        return LevelReservationResult(archive.stream_id, archive.record.digest, baseline.checkpoint_digest,
                                      baseline.pending_archive_digest, False)
    current = baseline.checkpoint_digest if baseline else None
    _require(expected_checkpoint == current, "Level checkpoint compare-and-swap conflict")
    _require(baseline is None or baseline.pending_archive_digest is None, "Level stream already has an unresolved pending update")
    if baseline is not None and baseline.accepted is not None:
        _check_before_checkpoint(archive, baseline.accepted)
    wanted_base = baseline.baseline_revision if baseline else archive.record.update_submission["original_publication"]["project"]["revision_id"]
    _require(archive.base == wanted_base, "Level update base differs from accepted stream revision")
    binding = archive.record.binding_dict()
    _require(connection.execute("SELECT digest FROM level_update_archives WHERE journal_id=? AND operation_id=?",
        (binding["target"]["journal_id"], binding["operation_id"])).fetchone() is None,
        "native operation identity is already reserved with another archive")
    if baseline is None:
        scope = _scope(archive.record.update_submission["original_publication"])
        for key in scope:
            _require(connection.execute("SELECT stream_id FROM level_scope_owners WHERE journal_id=? AND instance_id=? AND revit_version=? AND document_key=? AND unique_id=?", key).fetchone() is None,
                     "native UID scope is already owned by another Level stream")
        connection.execute("INSERT INTO level_streams VALUES (?, ?, NULL, NULL)", (archive.stream_id, archive.original_payload))
        for key in sorted(scope):
            connection.execute("INSERT INTO level_scope_owners VALUES (?, ?, ?, ?, ?, ?)", (*key, archive.stream_id))
    connection.execute("INSERT INTO level_update_archives VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (archive.record.digest, archive.stream_id, expected_checkpoint, archive.base, archive.proposed,
         binding["target"]["journal_id"], binding["operation_id"], archive.payload))
    changed = connection.execute("UPDATE level_streams SET pending_archive_digest=? WHERE stream_id=? AND checkpoint_digest IS ? AND pending_archive_digest IS NULL",
        (archive.record.digest, archive.stream_id, expected_checkpoint))
    _require(changed.rowcount == 1, "Level pending compare-and-swap conflict")
    return LevelReservationResult(archive.stream_id, archive.record.digest, current, archive.record.digest, True)


def settle(connection, state, prepared, expected_checkpoint, expected_pending_archive):
    _schema(state)
    _digest(expected_checkpoint, nullable=True)
    _digest(expected_pending_archive)
    archive, data, payload = prepared
    _require(expected_pending_archive == archive.record.digest, "settlement pending archive differs from qualified record")
    _check_projects(connection, state, archive)
    baseline = read_baseline(connection, state, archive.stream_id)
    prior = connection.execute("SELECT digest FROM level_settlements WHERE digest=?", (data["settlement_digest"],)).fetchone()
    if prior:
        old, original = _read_settlement(connection, state, data["settlement_digest"])
        _require(old[7] == payload and old[3] == expected_checkpoint and old[2] == expected_pending_archive,
                 "Level settlement replay differs from original reservation")
        return LevelSettlementResult(archive.stream_id, data["settlement_digest"], baseline.checkpoint_digest,
                                     baseline.pending_archive_digest, False)
    _require(baseline.checkpoint_digest == expected_checkpoint and baseline.pending_archive_digest == expected_pending_archive,
             "Level settlement checkpoint/pending compare-and-swap conflict")
    pending, stored = _read_archive(connection, state, expected_pending_archive)
    _require(stored.payload == archive.payload and pending[2] == expected_checkpoint,
             "qualified record differs from exact stored pending archive")
    sequence = 0 if expected_checkpoint is None else _checkpoint_stub(connection, expected_checkpoint, archive.stream_id)[0][4] + 1
    _require(sequence < (1 << 63), "Level settlement sequence exhausted")
    connection.execute("INSERT INTO level_settlements VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (data["settlement_digest"], archive.stream_id, expected_pending_archive, expected_checkpoint, sequence,
         archive.base, archive.proposed, payload))
    changed = connection.execute("UPDATE level_streams SET checkpoint_digest=?, pending_archive_digest=NULL WHERE stream_id=? AND checkpoint_digest IS ? AND pending_archive_digest=?",
        (data["settlement_digest"], archive.stream_id, expected_checkpoint, expected_pending_archive))
    _require(changed.rowcount == 1, "Level settlement compare-and-swap conflict")
    return LevelSettlementResult(archive.stream_id, data["settlement_digest"], data["settlement_digest"], None, True)


def resolve_not_started(connection, state, prepared, expected_checkpoint, expected_pending_archive):
    _resolution_schema(state)
    _digest(expected_checkpoint, nullable=True)
    _digest(expected_pending_archive)
    archive, data, payload = prepared
    _require(expected_pending_archive == archive.record.digest, "resolution pending archive differs from qualified record")
    _check_projects(connection, state, archive)
    baseline = read_baseline(connection, state, archive.stream_id)
    previous = connection.execute("SELECT digest FROM level_resolutions WHERE digest=?", (data["resolution_digest"],)).fetchone()
    if previous:
        row, _ = _read_resolution(connection, state, data["resolution_digest"])
        _require(row[4] == payload and row[3] == expected_checkpoint and row[1] == expected_pending_archive,
                 "Level resolution replay differs from original reservation")
        return LevelResolutionResult(archive.stream_id, data["resolution_digest"], baseline.checkpoint_digest,
                                     baseline.pending_archive_digest, False)
    _require(baseline.checkpoint_digest == expected_checkpoint and baseline.pending_archive_digest == expected_pending_archive,
             "Level not_started checkpoint/pending compare-and-swap conflict")
    pending, stored = _read_archive(connection, state, expected_pending_archive)
    _require(stored.payload == archive.payload and pending[2] == expected_checkpoint,
             "qualified not_started record differs from stored pending archive")
    connection.execute("INSERT INTO level_resolutions VALUES (?, ?, ?, ?, ?)",
        (data["resolution_digest"], expected_pending_archive, archive.stream_id, expected_checkpoint, payload))
    changed = connection.execute("UPDATE level_streams SET pending_archive_digest=NULL WHERE stream_id=? AND checkpoint_digest IS ? AND pending_archive_digest=?",
        (archive.stream_id, expected_checkpoint, expected_pending_archive))
    _require(changed.rowcount == 1, "Level not_started compare-and-swap conflict")
    return LevelResolutionResult(archive.stream_id, data["resolution_digest"], baseline.checkpoint_digest, None, True)


def read_resolution(connection, state, digest):
    _resolution_schema(state)
    _digest(digest)
    return _read_resolution(connection, state, digest)[1]


def read_resolution_for_archive(connection, state, archive_digest):
    _resolution_schema(state)
    _digest(archive_digest)
    _read_archive(connection, state, archive_digest)
    row = connection.execute("SELECT digest FROM level_resolutions WHERE archive_digest=?", (archive_digest,)).fetchone()
    return None if row is None else _read_resolution(connection, state, row[0])[1]


def read_update_archive(connection, state, digest):
    _schema(state)
    _digest(digest)
    return _read_archive(connection, state, digest)[1].record


def read_settlement(connection, state, digest):
    _schema(state)
    _digest(digest)
    return _read_settlement(connection, state, digest)[1]


def status_page(connection, state, *, limit, after_stream):
    """Bounded local projection in the caller's read transaction, never live BIM."""
    _schema(state)
    # An absent owner row must not make its unresolved operation disappear
    # from user status. These checks scan metadata, not historical payloads.
    tables = ["level_update_archives", "level_settlements", "level_scope_owners"]
    if state.schema in _RESOLUTION_SCHEMAS:
        tables.append("level_resolutions")
    orphaned = any(connection.execute(
        f"SELECT 1 FROM {table} AS item LEFT JOIN level_streams AS owner ON owner.stream_id=item.stream_id "
        "WHERE owner.stream_id IS NULL LIMIT 1").fetchone() is not None for table in tables)
    rows = connection.execute("SELECT stream_id FROM level_streams WHERE stream_id > ? ORDER BY stream_id LIMIT ?",
                              (after_stream or "", limit + 1)).fetchall()
    more = len(rows) > limit
    summaries = []
    for (stream_id,) in rows[:limit]:
        if type(stream_id) is not str or not _HEX64.fullmatch(stream_id):
            summaries.append({"stream_id": None, "state": "unavailable", "diagnostic": "invalid_stored_stream_id"})
            continue
        try:
            baseline = read_baseline(connection, state, stream_id)
        except (StoreCorrupt, StoreNotFound):
            summaries.append({"stream_id": stream_id, "state": "unavailable", "diagnostic": "stored_scope_unavailable"})
            continue
        original = baseline.original
        pending = None
        if baseline.pending_archive_digest is not None:
            # read_baseline validated these exact rows in THIS SQL snapshot.
            before, proposed, operation = connection.execute(
                "SELECT base_revision, proposed_revision, operation_id FROM level_update_archives WHERE digest=?",
                (baseline.pending_archive_digest,)).fetchone()
            pending = {"archive_digest": baseline.pending_archive_digest, "operation_id": operation,
                "base_revision": before, "proposed_revision": proposed,
                "execution": "not_established_by_reservation"}
        failed_attempts = 0
        if state.schema in _RESOLUTION_SCHEMAS:
            failed_attempts = connection.execute(
                "SELECT count(*) FROM level_resolutions WHERE stream_id=? AND expected_checkpoint IS ?",
                (stream_id, baseline.checkpoint_digest)).fetchone()[0]
        summaries.append({"stream_id": stream_id,
            "state": "pending" if pending is not None else "checkpoint_recorded" if baseline.accepted is not None else "not_started_only",
            "target": original["execution"]["target"],
            "document_key": original["execution"]["precondition"]["document_key"],
            "original_revision": original["project"]["revision_id"],
            "planning_base_revision": baseline.baseline_revision,
            "accepted_scope_revision": baseline.accepted["proposed_revision"] if baseline.accepted is not None else None,
            "checkpoint_digest": baseline.checkpoint_digest,
            "authoring_head_matches_planning_base": state.head.revision_id == baseline.baseline_revision,
            "outputs": [{key: row[key] for key in ("instance_key", "output_key", "output_id", "source_op")}
                        for row in original["outputs"]],
            "pending": pending, "not_started_at_checkpoint": failed_attempts,
            "evidence": "historical_selected_fields_not_current_model",
            "not_evaluated": ["dependent_geometry", "protected_geometry", "engineering"]})
    next_cursor = None
    if more:
        candidate = rows[limit - 1][0]
        if type(candidate) is str and _HEX64.fullmatch(candidate):
            next_cursor = candidate
    return {"streams": summaries, "has_more": more,
        "next_cursor": next_cursor,
        "catalog_complete": after_stream is None and not more and not orphaned,
        "returned_scopes_readable": not orphaned and all(row["state"] != "unavailable" for row in summaries),
        "catalog_diagnostic": "orphaned_scope_records" if orphaned else None,
        "continuation_consistency": "new_read_snapshot_each_call"}


def audit_streams(connection, state):
    """Explicit history audit includes all archives/checkpoints, not hot reads."""
    for (stream_id,) in connection.execute("SELECT stream_id FROM level_streams"):
        baseline = read_baseline(connection, state, stream_id)
        previous = None
        settled_archives = set()
        for index, (digest,) in enumerate(connection.execute("SELECT digest FROM level_settlements WHERE stream_id=? ORDER BY sequence", (stream_id,))):
            row, _ = _read_settlement(connection, state, digest)
            _require(row[3] == previous and row[4] == index, "Level settlement history has a gap or branch", stored=True)
            previous = digest
            settled_archives.add(row[2])
        _require(previous == baseline.checkpoint_digest, "Level accepted history differs from head", stored=True)
        archives = {row[0] for row in connection.execute("SELECT digest FROM level_update_archives WHERE stream_id=?", (stream_id,))}
        resolved_archives = set()
        if state.schema in _RESOLUTION_SCHEMAS:
            for (digest,) in connection.execute("SELECT digest FROM level_resolutions WHERE stream_id=?", (stream_id,)):
                row, _ = _read_resolution(connection, state, digest)
                resolved_archives.add(row[1])
        _require(not settled_archives & resolved_archives, "Level history has conflicting terminal outcomes", stored=True)
        for digest in archives:
            _read_archive(connection, state, digest)
        _require(archives == settled_archives | resolved_archives | ({baseline.pending_archive_digest} if baseline.pending_archive_digest else set()),
                 "Level archives include an orphan or abandoned reservation", stored=True)
