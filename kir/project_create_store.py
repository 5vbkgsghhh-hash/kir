"""Durable CREATE inputs/scopes in ProjectStore's existing transaction owner.

No connection, transport, compiler plan, recipe or native kernel is created
here. A reservation retains input and ownership, not proof of dispatch or a
retry ticket. Ownership is not released by time or by receipt presence.
"""
from dataclasses import dataclass, field
import sqlite3

from kir.project import _canonical, _object, _thaw, _hash
from kir.project_store import (CREATE_STORE_SCHEMA, CREATE_RESOLUTION_STORE_SCHEMA, STAGED_CREATE_STORE_SCHEMA,
    _CREATE_SCHEMAS, _CREATE_RESOLUTION_SCHEMAS, ProjectStoreError, StoreConflict,
    StoreCorrupt, StoreNotFound, StoreUpgradeRequired, _find_revision, _HEX64)
from kir.saved_execution import SavedExecutionRecord, SavedExecutionError, PROJECT_ARCHIVE_SCHEMA, MAX_RECORD_BYTES
from kir.revit_connector import MAX_FRAME_BYTES

MAX_CREATE_RECEIPT_BYTES = MAX_FRAME_BYTES + 8192
MAX_CREATE_PROGRESS_RECEIPTS = 32
# Payload memo is bounded; iterative traversal has no arbitrary legal DAG depth
# limit and never treats cache eviction as permission to skip qualification.
MAX_STAGED_IMPORT_MEMO_ENTRIES = 16


CREATE_TABLES = {
    "create_inputs": """CREATE TABLE create_inputs (
        archive_digest TEXT NOT NULL PRIMARY KEY CHECK (length(archive_digest) = 64),
        source_revision TEXT NOT NULL REFERENCES revisions(revision_id),
        journal_id TEXT NOT NULL,
        instance_id TEXT NOT NULL,
        revit_version TEXT NOT NULL,
        document_key TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE (journal_id, operation_id)
    )""",
    "create_scope_owners": """CREATE TABLE create_scope_owners (
        journal_id TEXT NOT NULL,
        instance_id TEXT NOT NULL,
        revit_version TEXT NOT NULL,
        document_key TEXT NOT NULL,
        output_id TEXT NOT NULL CHECK (length(output_id) = 64),
        archive_digest TEXT NOT NULL REFERENCES create_inputs(archive_digest),
        PRIMARY KEY (journal_id, instance_id, revit_version, document_key, output_id)
    )""",
    "create_receipts": """CREATE TABLE create_receipts (
        receipt_digest TEXT NOT NULL PRIMARY KEY CHECK (length(receipt_digest) = 64),
        archive_digest TEXT NOT NULL REFERENCES create_inputs(archive_digest),
        payload TEXT NOT NULL
    )""",
}

CREATE_RESOLUTION_TABLES = {
    "create_resolutions": """CREATE TABLE create_resolutions (
        archive_digest TEXT NOT NULL PRIMARY KEY REFERENCES create_inputs(archive_digest) CHECK (length(archive_digest) = 64),
        receipt_digest TEXT NOT NULL UNIQUE REFERENCES create_receipts(receipt_digest) CHECK (length(receipt_digest) = 64)
    )""",
}

CREATE_IMPORT_TABLES = {
    "create_imports": """CREATE TABLE create_imports (
        archive_digest TEXT NOT NULL REFERENCES create_inputs(archive_digest) CHECK (length(archive_digest) = 64),
        output_id TEXT NOT NULL CHECK (length(output_id) = 64),
        original_archive_digest TEXT NOT NULL REFERENCES create_inputs(archive_digest) CHECK (length(original_archive_digest) = 64),
        original_receipt_digest TEXT NOT NULL REFERENCES create_receipts(receipt_digest) CHECK (length(original_receipt_digest) = 64),
        PRIMARY KEY (archive_digest, output_id)
    )""",
}


def create_tables(schema):
    if schema == CREATE_STORE_SCHEMA:
        return dict(CREATE_TABLES)
    if schema == CREATE_RESOLUTION_STORE_SCHEMA:
        return {**CREATE_TABLES, **CREATE_RESOLUTION_TABLES}
    if schema == STAGED_CREATE_STORE_SCHEMA:
        return {**CREATE_TABLES, **CREATE_RESOLUTION_TABLES, **CREATE_IMPORT_TABLES}
    raise StoreUpgradeRequired("unsupported CREATE ledger schema")


@dataclass(frozen=True, slots=True)
class CreateReservationResult:
    archive_digest: str
    inserted: bool
    output_ids: tuple[str, ...]
    may_retry: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class RecordedCreatePublication:
    """Inert checked archive/source association, never a prepared execution."""
    store_id: str
    project_id: str
    record: SavedExecutionRecord
    source_revision: str
    output_ids: tuple[str, ...]
    state: str = "reserved"
    may_retry: bool = field(default=False, init=False)

    @property
    def archive_digest(self):
        return self.record.digest

    def to_dict(self):
        return {"schema": "kir-recorded-create-publication/1", "store_id": self.store_id,
            "project_id": self.project_id, "archive_digest": self.archive_digest,
            "source_revision": self.source_revision, "output_ids": list(self.output_ids),
            "state": self.state, "input": self.record.to_dict(), "may_retry": False,
            "claims": {"scope": ("reserved_authored_outputs_in_native_namespace" if self.state == "reserved"
                                  else "original_output_scope_released_by_retained_no_start"),
                       "execution": "not_established", "native_acceptance": "not_established",
                       "receipt_evidence": ("not_read_by_input_api" if self.state == "reserved"
                                            else "retained_no_start_link_checked"), "dispatch_permission": "none"}}


@dataclass(frozen=True, slots=True)
class CreateReceiptRecordResult:
    archive_digest: str
    receipt_digest: str
    terminal_receipt_digest: str | None
    inserted: bool
    may_retry: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class CreateResolutionResult:
    archive_digest: str
    receipt_digest: str
    inserted: bool
    may_retry: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class RecordedCreateResolution:
    archive_digest: str
    receipt_digest: str

    def to_dict(self):
        return {"schema": "kir-recorded-create-resolution/1", "archive_digest": self.archive_digest,
                "receipt_digest": self.receipt_digest, "state": "released_not_started",
                "claims": {"evidence": "retained_no_start_association_not_fresh_authentication",
                           "dispatch_permission": "none", "retry_permission": "none"}}


@dataclass(frozen=True, slots=True)
class RecordedCreateReceipts:
    archive_digest: str
    terminal_receipt_digest: str | None
    _payload: object = field(repr=False)

    def to_dict(self):
        return {"schema": "kir-recorded-create-receipts/1", "archive_digest": self.archive_digest,
                "terminal_receipt_digest": self.terminal_receipt_digest, "receipts": _thaw(self._payload)["receipts"],
                "claims": {"evidence": "retained_claims_not_fresh_observation", "native_acceptance": "not_established",
                           "scope_ownership": "unchanged", "dispatch_permission": "none", "retry_permission": "none"}}


@dataclass(frozen=True, slots=True)
class _Input:
    record: SavedExecutionRecord
    payload: str
    source_revision: str
    namespace: tuple[str, str, str, str]
    operation_id: str
    output_ids: tuple[str, ...]


def _require(value, message, *, stored=False):
    if not value:
        raise (StoreCorrupt if stored else StoreConflict)(message)


def _digest(value):
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ProjectStoreError("expected a lowercase SHA-256 identity")


def _transaction(connection, state):
    if state.schema not in _CREATE_SCHEMAS:
        raise StoreUpgradeRequired("CREATE reservations require explicit kir-project-store/6 upgrade")
    if not connection.in_transaction:
        raise ProjectStoreError("CREATE ledger requires an existing ProjectStore transaction")


def checked_input(record, *, stored=False):
    """Validate retained Archive/2 bytes only, never the current registry."""
    error_type = StoreCorrupt if stored else ProjectStoreError
    if type(record) is not SavedExecutionRecord:
        raise error_type("CREATE reservation requires exact SavedExecutionRecord")
    try:
        checked = SavedExecutionRecord._from_bytes(record._raw)
        if checked.digest != record.digest:
            raise ValueError("archive identity differs")
        data = checked.to_dict()
        if data["schema"] != PROJECT_ARCHIVE_SCHEMA:
            raise ValueError("Archive/2 required")
        payload = _canonical(data)
        checked = SavedExecutionRecord._from_bytes(payload.encode("utf-8"))
        binding, submission = data["binding"], data["project_submission"]
        target = binding["target"]
        outputs = tuple(row["output_id"] for row in submission["outputs"])
        if not outputs or len(set(outputs)) != len(outputs):
            raise ValueError("empty/repeated output scope")
        return _Input(checked, payload, submission["project"]["revision_id"],
            (target["journal_id"], target["instance_id"], target["revit_version"], binding["precondition"]["document_key"]),
            binding["operation_id"], outputs)
    except (SavedExecutionError, TypeError, ValueError, KeyError, UnicodeError) as error:
        raise error_type("invalid retained CREATE input archive") from error


def _staged(value):
    from kir.staged_submission import STAGED_SUBMISSION_SCHEMA
    return value.record.project_submission["schema"] == STAGED_SUBMISSION_SCHEMA


def checked_submission(value, submission):
    """Check a supplied fresh binding before entering a SQL transaction.

    The staged factory already re-prepared the exact runtime source. No compiler
    runs here or under the writer lock. None remains valid for historical replay.
    """
    if submission is None:
        return None
    from kir.project_submission import SubmittedProjectBinding
    _require(type(submission) is SubmittedProjectBinding
             and _canonical(submission.to_dict()) == _canonical(value.record.project_submission),
             "fresh CREATE submission differs from the exact retained input")
    return submission


def _source(connection, state, value, *, stored, current=False):
    from kir.project_submission import validate_submission_source
    actual = _find_revision(connection, state, value.source_revision)
    _require(actual is not None, "CREATE source is not in the stored authored history", stored=stored)
    try:
        validate_submission_source(actual, value.record.project_submission,
                                   selection_policy="current" if current else "retained")
    except ValueError as error:
        raise (StoreCorrupt if stored else StoreConflict)("CREATE archive differs from its actual stored source") from error
    return actual


def _input_row(connection, digest):
    size = connection.execute("SELECT length(CAST(payload AS BLOB)) FROM create_inputs WHERE archive_digest=?", (digest,)).fetchone()
    if size is None:
        return None
    if type(size[0]) is not int or not 0 < size[0] <= MAX_RECORD_BYTES:
        raise StoreCorrupt("stored CREATE input exceeds its bounded archive size")
    limit = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(limit, MAX_RECORD_BYTES + 8192))
    try:
        return connection.execute("SELECT archive_digest,source_revision,journal_id,instance_id,revit_version,document_key,operation_id,payload FROM create_inputs WHERE archive_digest=?", (digest,)).fetchone()
    except sqlite3.DataError as error:
        raise StoreCorrupt("stored CREATE input row exceeds its SQLite size bound") from error
    finally:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, limit)


def _read_input_base(connection, state, digest):
    row = _input_row(connection, digest)
    if row is None:
        raise StoreNotFound("CREATE publication is not in this store")
    try:
        record = SavedExecutionRecord._from_bytes(row[7].encode("utf-8"))
        value = checked_input(record, stored=True)
        _require(row == (value.record.digest, value.source_revision, *value.namespace, value.operation_id, value.payload),
                 "CREATE indexed metadata differs from retained input", stored=True)
        _require(value.record.digest == digest, "CREATE lookup returned another archive", stored=True)
    except (SavedExecutionError, TypeError, ValueError, AttributeError) as error:
        raise StoreCorrupt("stored CREATE input is malformed") from error
    _source(connection, state, value, stored=True)
    resolution = _resolution(connection, state, value)
    count = connection.execute("SELECT count(*) FROM create_scope_owners WHERE archive_digest=?", (digest,)).fetchone()[0]
    _require(count == (len(value.output_ids) if resolution is None else 0), "CREATE scope has missing or extra owner rows", stored=True)
    wanted = {(*value.namespace, oid, digest) for oid in value.output_ids} if resolution is None else set()
    limit = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    row_budget = max(4096, sum(len(part.encode("utf-8")) for part in value.namespace) + 512)
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(limit, row_budget))
    try:
        actual = set(connection.execute("SELECT journal_id,instance_id,revit_version,document_key,output_id,archive_digest FROM create_scope_owners WHERE archive_digest=?", (digest,)))
    except sqlite3.DataError as error:
        raise StoreCorrupt("stored CREATE scope row exceeds its bounded identity fields") from error
    finally:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, limit)
    _require(actual == wanted, "CREATE scope owner identities differ from retained input", stored=True)
    return value


def _import_audit():
    """Memoization belongs to ONE caller-owned SQL snapshot, never a process."""
    return {"inputs": {}, "active": set(), "verified": set(), "receipts": {}, "identities": {}, "sources": {}}


def _memo(audit, name, key, value):
    # Eviction only repeats validation; it never turns absent data into success.
    # Keep neither every archive nor every decoded receipt in a large catalog.
    bucket = audit[name]
    if key not in bucket and len(bucket) >= MAX_STAGED_IMPORT_MEMO_ENTRIES:
        bucket.pop(next(iter(bucket)))
    bucket[key] = value
    return value


def _read_input(connection, state, digest, *, audit=None):
    if state.schema != STAGED_CREATE_STORE_SCHEMA:
        return _read_input_base(connection, state, digest)
    audit = _import_audit() if audit is None else audit
    _require(digest not in audit["active"], "cyclic stored CREATE import lineage", stored=True)
    if digest in audit["verified"]:
        if digest not in audit["inputs"]:
            _memo(audit, "inputs", digest, _read_input_base(connection, state, digest))
        return audit["inputs"][digest]
    # Keep only digest/phase pairs for ancestors, not every decoded archive.
    # Dependencies complete before their consumer; a diamond is checked once in
    # this SQL snapshot even if its payload was evicted from the small memo.
    stack, entered = [(digest, False)], set()
    try:
        while stack:
            current, finish = stack.pop()
            if finish:
                value = _read_input_base(connection, state, current)
                _check_imports(connection, state, value, audit=audit, stored=True, check_index=True)
                audit["active"].remove(current)
                audit["verified"].add(current)
                _memo(audit, "inputs", current, value)
                continue
            if current in audit["verified"]:
                continue
            _require(current not in audit["active"], "cyclic stored CREATE import lineage", stored=True)
            audit["active"].add(current)
            entered.add(current)
            try:
                value = _read_input_base(connection, state, current)
            except StoreNotFound as error:
                if current != digest:
                    raise StoreCorrupt("stored staged original CREATE input is missing") from error
                raise
            core = value.record.project_submission.get("projection", {}).get("association_core", {}) if _staged(value) else {}
            dependencies = sorted({row["original_archive_digest"] for row in core.get("import_lineage", [])})
            del value
            stack.append((current, True))
            stack.extend((original, False) for original in reversed(dependencies))
        return audit["inputs"][digest]
    finally:
        audit["active"].difference_update(entered)


def _import_index(connection):
    _require(connection.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='create_imports'").fetchone() is not None,
             "stored staged CREATE import table is missing; no implicit repair", stored=True)
    orphan = connection.execute("""SELECT 1 FROM create_imports AS edge
        LEFT JOIN create_inputs AS child ON child.archive_digest=edge.archive_digest
        LEFT JOIN create_inputs AS original ON original.archive_digest=edge.original_archive_digest
        LEFT JOIN create_receipts AS receipt ON receipt.receipt_digest=edge.original_receipt_digest
        WHERE child.archive_digest IS NULL OR original.archive_digest IS NULL
           OR receipt.receipt_digest IS NULL OR receipt.archive_digest!=edge.original_archive_digest LIMIT 1""").fetchone()
    _require(orphan is None, "stored CREATE import has missing or different input/receipt owner", stored=True)


def _source_addresses(connection, state, value, audit, *, stored):
    revision = value.source_revision
    if revision not in audit["sources"]:
        source = _source(connection, state, value, stored=stored)
        modules = {module.key: module for module in source.modules}
        addresses = {oid: (instance, output, modules[instance.module_key])
                     for instance, output, oid in source.addressed_outputs()}
        _memo(audit, "sources", revision, (source, addresses))
    return audit["sources"][revision]


def _check_imports(connection, state, value, *, audit, stored, check_index):
    """Check actual retained originals, not a second native identity judge."""
    from kir.create_publication import retained_create_identity_claims

    core = (value.record.project_submission["projection"]["association_core"] if _staged(value) else None)
    lineage = core["import_lineage"] if core is not None else []
    expected = {(value.record.digest, row["output_id"], row["original_archive_digest"], row["original_receipt_digest"])
                for row in lineage}
    if check_index:
        count = connection.execute("SELECT count(*) FROM create_imports WHERE archive_digest=?", (value.record.digest,)).fetchone()[0]
        _require(count == len(expected), "stored CREATE import index has missing or extra links", stored=True)
        limit = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(limit, 1024))
        try:
            actual = set(connection.execute("SELECT archive_digest,output_id,original_archive_digest,original_receipt_digest FROM create_imports WHERE archive_digest=?", (value.record.digest,)))
        except sqlite3.DataError as error:
            raise StoreCorrupt("stored CREATE import identity exceeds its bounded size") from error
        finally:
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, limit)
        _require(actual == expected, "stored CREATE import index differs from retained lineage", stored=True)
    if not lineage:
        return expected
    child_source, child_addresses = _source_addresses(connection, state, value, audit, stored=stored)
    for row in lineage:
        oid, original_digest, receipt_digest = (row[key] for key in
            ("output_id", "original_archive_digest", "original_receipt_digest"))
        _require(oid not in value.output_ids, "staged imported output cannot acquire child export ownership", stored=stored)
        try:
            original = _read_input(connection, state, original_digest, audit=audit)
        except StoreNotFound as error:
            raise (StoreCorrupt if stored else StoreConflict)("staged original CREATE input is missing") from error
        _require(_resolution(connection, state, original) is None,
                 "staged original CREATE scope was released", stored=stored)
        _require(original.namespace == value.namespace
                 and original.source_revision == row["original_project_revision"]
                 and oid in original.output_ids,
                 "staged original namespace, revision or published output differs", stored=stored)
        original_source, original_addresses = _source_addresses(connection, state, original, audit, stored=stored)
        old = original_addresses.get(oid)
        current = child_addresses.get(oid)
        _require(old is not None and current is not None
                 and original_source.project_id == child_source.project_id == state.project_id,
                 "staged original source address belongs to another project", stored=stored)
        old_instance, old_output, old_module = old
        current_instance, current_output, current_module = current
        _require((old_instance.key, old_output.key) == (row["instance_key"], row["output_key"])
                 == (current_instance.key, current_output.key)
                 and old_instance.module_key == current_instance.module_key
                 and _canonical(old_output.to_dict()) == _canonical(current_output.to_dict())
                 and old_module.definition_digest == current_module.definition_digest == row["module_definition_digest"]
                 and _hash(old_instance.parameters) == _hash(current_instance.parameters) == row["instance_parameters_digest"]
                 and _hash({**_thaw(old_output.operation), "id": oid}) == row["source_operation_digest"],
                 "staged original authored operation or module/parameter ownership differs", stored=stored)
        original_binding = original.record.binding_dict()
        _require(_canonical(original_binding["precondition"]) == _canonical(row["original_precondition"]),
                 "staged original precondition differs from retained CREATE input", stored=stored)
        if original_digest not in audit["receipts"]:
            _memo(audit, "receipts", original_digest, _receipt_rows(connection, original))
        receipts, terminal = audit["receipts"][original_digest]
        claim = next((item for item in receipts if item["receipt_digest"] == receipt_digest), None)
        _require(claim is not None and terminal == receipt_digest,
                 "staged original bound terminal CREATE receipt is missing or different", stored=stored)
        key = original_digest, receipt_digest
        if key not in audit["identities"]:
            try:
                _memo(audit, "identities", key, retained_create_identity_claims(original_source, original.record, claim))
            except (ValueError, TypeError, KeyError) as error:
                raise (StoreCorrupt if stored else StoreConflict)("staged original retained identity claims are invalid") from error
        assessment = audit["identities"][key]
        qualified = next((item for item in assessment["outputs"] if item["output_id"] == oid), None)
        _require(assessment["assessment_digest"] == row["original_identity_assessment_digest"]
                 and qualified is not None and qualified["state"] in ("created_here", "reused_existing")
                 and qualified["state"] == row["original_identity_state"]
                 and _canonical(qualified["element_identity"]) == _canonical(row["original_identity"]),
                 "staged original identity assessment, state or proof differs", stored=stored)
        changes = claim["native_receipt"]["changes"]
        unchanged_reuse = (qualified["state"] == "reused_existing" and changes["truncated"] is False
            and all(not changes[field] for field in ("added", "modified", "deleted", "transaction_names")))
        before, now = original_binding["precondition"]["revision"], core["precondition"]["revision"]
        _require(now > before or now == before and unchanged_reuse,
                 "staged observation predates creation or changed type reuse", stored=stored)
    return expected


def audit_inputs(connection, state):
    """Check the whole ownership catalog before deciding any output is free."""
    _transaction(connection, state)
    audit = _import_audit() if state.schema == STAGED_CREATE_STORE_SCHEMA else None
    if audit is not None:
        _import_index(connection)
    if connection.execute("SELECT 1 FROM create_scope_owners o LEFT JOIN create_inputs i ON i.archive_digest=o.archive_digest WHERE i.archive_digest IS NULL LIMIT 1").fetchone():
        raise StoreCorrupt("CREATE scope owner has no retained input")
    _audit_receipt_index(connection)
    if state.schema in _CREATE_RESOLUTION_SCHEMAS:
        if connection.execute("SELECT 1 FROM create_resolutions x LEFT JOIN create_inputs i ON i.archive_digest=x.archive_digest LEFT JOIN create_receipts r ON r.receipt_digest=x.receipt_digest WHERE i.archive_digest IS NULL OR r.receipt_digest IS NULL OR r.archive_digest!=x.archive_digest LIMIT 1").fetchone():
            raise StoreCorrupt("CREATE resolution has missing or different input/receipt owner")
    for (digest,) in connection.execute("SELECT archive_digest FROM create_inputs ORDER BY archive_digest"):
        _read_input(connection, state, digest, audit=audit)
    if connection.execute("SELECT 1 FROM create_inputs c JOIN level_update_archives l ON l.journal_id=c.journal_id AND l.operation_id=c.operation_id LIMIT 1").fetchone():
        raise StoreCorrupt("one native operation UUID belongs to CREATE and Level inputs")
    return audit


def _audit_receipt_index(connection):
    """A lookup must not hide a receipt moved to a different indexed input.

    This is a streaming catalog scan, not an O(selected) lookup. Bound each
    payload before loading it; full native receipt validation is separate.
    """
    from kir.connector_result import _json
    if connection.execute("SELECT 1 FROM create_receipts r LEFT JOIN create_inputs i ON i.archive_digest=r.archive_digest WHERE i.archive_digest IS NULL LIMIT 1").fetchone():
        raise StoreCorrupt("CREATE receipt has no retained input")
    if connection.execute("SELECT 1 FROM create_receipts WHERE length(CAST(payload AS BLOB)) NOT BETWEEN 1 AND ? LIMIT 1", (MAX_CREATE_RECEIPT_BYTES,)).fetchone():
        raise StoreCorrupt("CREATE receipt exceeds its bounded payload size")
    limit = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(limit, MAX_CREATE_RECEIPT_BYTES + 8192))
    try:
        for digest, archive_digest, payload in connection.execute("SELECT receipt_digest,archive_digest,payload FROM create_receipts"):
            try:
                parsed, _ = _json(payload, MAX_CREATE_RECEIPT_BYTES)
                _require(type(parsed) is dict and parsed.get("archive_digest") == archive_digest
                         and parsed.get("receipt_digest") == digest,
                         "CREATE receipt indexed metadata differs from retained payload", stored=True)
            except (ValueError, TypeError) as error:
                raise StoreCorrupt("stored CREATE receipt index payload is malformed") from error
    except sqlite3.DataError as error:
        raise StoreCorrupt("stored CREATE receipt index row exceeds its size bound") from error
    finally:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, limit)


def audit_publications(connection, state):
    """Full explicit history audit, including retained receipt content."""
    audit = audit_inputs(connection, state)
    for (digest,) in connection.execute("SELECT archive_digest FROM create_inputs ORDER BY archive_digest"):
        _receipt_rows(connection, _read_input(connection, state, digest, audit=audit))


def require_native_operation_available(connection, state, journal_id, operation_id):
    """Level reservation's cross-method check, in the same writer transaction."""
    if state.schema not in _CREATE_SCHEMAS:
        return
    audit_inputs(connection, state)
    _require(connection.execute("SELECT 1 FROM create_inputs WHERE journal_id=? AND operation_id=?", (journal_id, operation_id)).fetchone() is None,
             "native operation identity is already reserved by a CREATE input")


def reserve(connection, state, value, expected_revision, *, submission=None):
    _transaction(connection, state)
    _digest(expected_revision)
    audit = audit_inputs(connection, state)
    _require(expected_revision == value.source_revision, "CREATE expected revision differs from archived source")
    existing = connection.execute("SELECT 1 FROM create_inputs WHERE archive_digest=?", (value.record.digest,)).fetchone()
    if existing:
        previous = _read_input(connection, state, value.record.digest, audit=audit)
        _require(previous.payload == value.payload, "CREATE replay differs from retained input")
        return CreateReservationResult(value.record.digest, False, previous.output_ids)
    if _staged(value):
        if state.schema != STAGED_CREATE_STORE_SCHEMA:
            raise StoreUpgradeRequired("staged CREATE imports require explicit kir-project-store/8 upgrade")
        _require(submission is not None, "first staged CREATE reservation requires an exact fresh submission binding")
    _require(state.head.revision_id == expected_revision, "CREATE first reservation requires the current authored head")
    _source(connection, state, value, stored=False, current=not _staged(value))
    imports = (_check_imports(connection, state, value, audit=audit, stored=False, check_index=False)
               if _staged(value) else ())
    from kir.bridge_result import saved_create_result_contract
    try:
        expected = saved_create_result_contract(value.record)
    except ValueError as error:
        raise StoreConflict("CREATE input does not satisfy the current flat CREATE result contract") from error
    _require(tuple(expected) == value.output_ids, "CREATE compiled result coverage differs from source output scope")
    journal = value.namespace[0]
    _require(connection.execute("SELECT 1 FROM level_update_archives WHERE journal_id=? AND operation_id=?", (journal, value.operation_id)).fetchone() is None,
             "native operation identity is already reserved by a Level update")
    _require(connection.execute("SELECT 1 FROM create_inputs WHERE journal_id=? AND operation_id=?", (journal, value.operation_id)).fetchone() is None,
             "native operation identity is already reserved with another CREATE archive")
    for oid in value.output_ids:
        _require(connection.execute("SELECT 1 FROM create_scope_owners WHERE journal_id=? AND instance_id=? AND revit_version=? AND document_key=? AND output_id=?", (*value.namespace, oid)).fetchone() is None,
                 "CREATE output scope is already owned in this native namespace")
    connection.execute("INSERT INTO create_inputs VALUES (?,?,?,?,?,?,?,?)", (value.record.digest, value.source_revision, *value.namespace, value.operation_id, value.payload))
    connection.executemany("INSERT INTO create_scope_owners VALUES (?,?,?,?,?,?)", [(*value.namespace, oid, value.record.digest) for oid in value.output_ids])
    if imports:
        connection.executemany("INSERT INTO create_imports VALUES (?,?,?,?)", sorted(imports))
    return CreateReservationResult(value.record.digest, True, value.output_ids)


def read_publication(connection, state, digest):
    _transaction(connection, state)
    _digest(digest)
    audit_inputs(connection, state)
    value = _read_input(connection, state, digest)
    return _publication(connection, state, value)


def find_publication(connection, state, *, journal_id, operation_id):
    """Resolve the caller-known operation after a lost first-send/local ACK."""
    from kir.revit_connector import _uuid
    _transaction(connection, state)
    try:
        _require(_uuid(journal_id, "journal_id") == journal_id
                 and _uuid(operation_id, "operation_id") == operation_id,
                 "CREATE lookup requires canonical native operation identity")
    except ValueError as error:
        raise ProjectStoreError("CREATE lookup requires canonical native operation identity") from error
    audit_inputs(connection, state)
    row = connection.execute("SELECT archive_digest FROM create_inputs WHERE journal_id=? AND operation_id=?",
                             (journal_id, operation_id)).fetchone()
    if row is None:
        raise StoreNotFound("CREATE operation is not in this store")
    value = _read_input(connection, state, row[0])
    return _publication(connection, state, value)


def _receipt_rows(connection, value):
    from kir.connector_result import _json, native_receipt_terminal_state
    from kir.create_publication import validate_create_receipt_claims
    size = connection.execute("SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0),coalesce(max(length(CAST(payload AS BLOB))),0) FROM create_receipts WHERE archive_digest=?", (value.record.digest,)).fetchone()
    _require(size[0] <= MAX_CREATE_PROGRESS_RECEIPTS + 1 and size[1] <= 2 * MAX_CREATE_RECEIPT_BYTES
             and size[2] <= MAX_CREATE_RECEIPT_BYTES, "CREATE receipt storage budget exceeded", stored=True)
    rows, terminal = [], None
    progress_count, progress_bytes = 0, 0
    limit = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(limit, MAX_CREATE_RECEIPT_BYTES + 8192))
    try:
        stored_rows = connection.execute("SELECT receipt_digest,archive_digest,payload FROM create_receipts WHERE archive_digest=? ORDER BY receipt_digest", (value.record.digest,)).fetchall()
    except sqlite3.DataError as error:
        raise StoreCorrupt("stored CREATE receipt row exceeds its size bound") from error
    finally:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, limit)
    for digest, archive_digest, payload in stored_rows:
        try:
            parsed, _ = _json(payload, MAX_CREATE_RECEIPT_BYTES)
            validate_create_receipt_claims(value.record, parsed)
            _require(_canonical(parsed) == payload and digest == parsed["receipt_digest"]
                     and archive_digest == value.record.digest, "CREATE receipt indexed metadata differs", stored=True)
        except (ValueError, TypeError, KeyError) as error:
            raise StoreCorrupt("stored CREATE receipt claims are malformed") from error
        if native_receipt_terminal_state(parsed["native_receipt"]) is not None:
            _require(terminal is None, "conflicting terminal CREATE receipts", stored=True)
            terminal = digest
        else:
            progress_count += 1
            progress_bytes += len(payload.encode("utf-8"))
            _require(progress_count <= MAX_CREATE_PROGRESS_RECEIPTS
                     and progress_bytes <= MAX_CREATE_RECEIPT_BYTES,
                     "CREATE progress receipts exceed reserved progress capacity", stored=True)
        rows.append(parsed)
    return rows, terminal


def record_receipt(connection, state, evidence):
    """Append a bound receipt fact; never release owners or grant another send."""
    from kir.create_publication import BoundCreateReceipt, validate_create_receipt_claims
    from kir.connector_result import native_receipt_terminal_state
    _transaction(connection, state)
    if type(evidence) is not BoundCreateReceipt:
        raise ProjectStoreError("new bound CREATE receipt required, not loaded claims")
    audit_inputs(connection, state)
    value = _read_input(connection, state, evidence.archive_digest)
    data = evidence.to_dict()
    try:
        validate_create_receipt_claims(value.record, data)
        _require(data["receipt_digest"] == evidence.receipt_digest, "CREATE receipt object identity differs")
    except ValueError as error:
        raise StoreConflict("CREATE receipt differs from its reserved input") from error
    payload = _canonical(data)
    _require(len(payload.encode("utf-8")) <= MAX_CREATE_RECEIPT_BYTES, "CREATE receipt exceeds its storage budget")
    rows, terminal = _receipt_rows(connection, value)
    for row in rows:
        if row["receipt_digest"] == evidence.receipt_digest:
            _require(_canonical(row) == payload, "CREATE receipt digest has different retained content")
            return CreateReceiptRecordResult(value.record.digest, evidence.receipt_digest, terminal, False)
    incoming_terminal = native_receipt_terminal_state(data["native_receipt"]) is not None
    _require(not (incoming_terminal and terminal is not None), "another terminal receipt already owns this CREATE input")
    progress = [row for row in rows if native_receipt_terminal_state(row["native_receipt"]) is None]
    if not incoming_terminal:
        _require(len(progress) < MAX_CREATE_PROGRESS_RECEIPTS
                 and sum(len(_canonical(row).encode("utf-8")) for row in progress) + len(payload.encode("utf-8")) <= MAX_CREATE_RECEIPT_BYTES,
                 "CREATE progress receipt budget exhausted; terminal capacity is reserved")
    connection.execute("INSERT INTO create_receipts VALUES (?,?,?)", (evidence.receipt_digest, value.record.digest, payload))
    return CreateReceiptRecordResult(value.record.digest, evidence.receipt_digest,
                                     evidence.receipt_digest if incoming_terminal else terminal, True)


def read_receipts(connection, state, digest):
    _transaction(connection, state)
    _digest(digest)
    audit_inputs(connection, state)
    value = _read_input(connection, state, digest)
    rows, terminal = _receipt_rows(connection, value)
    return RecordedCreateReceipts(digest, terminal, _object({"receipts": rows}, "create_receipts"))


def _resolution(connection, state, value):
    """Read linked no-start evidence without recursing through input ownership."""
    if state.schema not in _CREATE_RESOLUTION_SCHEMAS:
        return None
    digest = value.record.digest
    shape = connection.execute("SELECT typeof(receipt_digest),length(CAST(receipt_digest AS BLOB)) FROM create_resolutions WHERE archive_digest=?", (digest,)).fetchone()
    if shape is None:
        return None
    _require(shape == ("text", 64), "CREATE resolution identity is malformed", stored=True)
    receipt_digest, = connection.execute("SELECT receipt_digest FROM create_resolutions WHERE archive_digest=?", (digest,)).fetchone()
    _require(_HEX64.fullmatch(receipt_digest) is not None, "CREATE resolution receipt digest is malformed", stored=True)
    receipts, terminal = _receipt_rows(connection, value)
    row = next((item for item in receipts if item["receipt_digest"] == receipt_digest), None)
    _require(row is not None and terminal == receipt_digest, "CREATE resolution does not name its retained terminal receipt", stored=True)
    from kir.create_publication import validate_create_not_started_claims
    try:
        validate_create_not_started_claims(value.record, row)
    except (ValueError, TypeError, KeyError) as error:
        raise StoreCorrupt("CREATE resolution no-start evidence is invalid") from error
    return RecordedCreateResolution(digest, receipt_digest)


def _publication(connection, state, value):
    resolved = _resolution(connection, state, value)
    return RecordedCreatePublication(state.store_id, state.project_id, value.record, value.source_revision,
        value.output_ids, "reserved" if resolved is None else "released_not_started")


def _require_resolution_schema(connection, state):
    _transaction(connection, state)
    if state.schema not in _CREATE_RESOLUTION_SCHEMAS:
        raise StoreUpgradeRequired("CREATE scope release requires explicit kir-project-store/7 upgrade")


def read_resolution(connection, state, digest):
    _require_resolution_schema(connection, state)
    _digest(digest)
    audit_inputs(connection, state)
    value = _read_input(connection, state, digest)
    return _resolution(connection, state, value)


def release_not_started(connection, state, evidence, expected_archive_digest):
    """Atomic receipt + immutable marker + exact owner release; never resend.

    Native UUID/input remain reserved after release. Replaying this resolution
    cannot delete a later publication's owners or claim the former call stopped
    unless its own bound no-start evidence establishes that fact.
    """
    from kir.create_publication import BoundCreateReceipt, require_create_not_started
    _require_resolution_schema(connection, state)
    _digest(expected_archive_digest)
    if type(evidence) is not BoundCreateReceipt:
        raise ProjectStoreError("fresh bound CREATE receipt required for scope release")
    _require(evidence.archive_digest == expected_archive_digest, "CREATE release expected another exact archive")
    audit_inputs(connection, state)
    value = _read_input(connection, state, expected_archive_digest)
    try:
        require_create_not_started(value.record, evidence)
    except (ValueError, TypeError, KeyError) as error:
        raise StoreConflict("CREATE release requires original bound native no-start evidence") from error
    prior = _resolution(connection, state, value)
    if prior is not None:
        _require(prior.receipt_digest == evidence.receipt_digest, "CREATE resolution replay names another receipt")
        return CreateResolutionResult(value.record.digest, prior.receipt_digest, False)
    saved = record_receipt(connection, state, evidence)
    _require(saved.terminal_receipt_digest == evidence.receipt_digest, "CREATE no-start receipt is not the terminal fact")
    connection.execute("INSERT INTO create_resolutions VALUES (?,?)", (value.record.digest, evidence.receipt_digest))
    deleted = connection.executemany(
        "DELETE FROM create_scope_owners WHERE journal_id=? AND instance_id=? AND revit_version=? AND document_key=? AND output_id=? AND archive_digest=?",
        [(*value.namespace, oid, value.record.digest) for oid in value.output_ids])
    _require(deleted.rowcount == len(value.output_ids), "CREATE release did not remove its exact complete owner set", stored=True)
    _read_input(connection, state, value.record.digest)  # Validate the final linked state before COMMIT.
    return CreateResolutionResult(value.record.digest, evidence.receipt_digest, True)
