"""One immutable, credential-free execution input in a new SQLite archive.

This preserves lookup identity/source across a Python crash, not dispatch state
or retry permission. Loaded claims never become PreparedExecution. SQLite/VFS
commit durability is not a power-loss guarantee; failed initialization is kept
for inspection and is never recovered, overwritten or repaired by this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat

from kir.midend import PLAN_SCHEMA, LINEAGED_PLAN_SCHEMA, GROUND_SCHEMA, LINEAGE_FORM
from kir.revit_connector import (CONNECTOR_PROTOCOL, MAX_SOURCE_CHARS, ContextPrecondition,
    PreparedExecution, RuntimeTarget, SessionCredentials, _request, _uuid)


ARCHIVE_SCHEMA = "kir-saved-execution/1"
PROJECT_ARCHIVE_SCHEMA = "kir-saved-execution/2"
UPDATE_ARCHIVE_SCHEMA = "kir-saved-execution/3"
MAX_RECORD_BYTES = 64 * 1024 * 1024
MAX_DATABASE_BYTES = 80 * 1024 * 1024
_APPLICATION_ID = 0x4B495253  # KIRS; not the ProjectStore KIRP identity.
_TABLE_SQL = """CREATE TABLE saved_execution (
    singleton INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
    payload TEXT NOT NULL
)"""
_CLAIMS = {"scope": "original_execution_input_archive", "compiler_evidence": "retained_claims_not_replayed",
    "native_execution": "not_established", "dispatch_state": "not_recorded", "retry_permission": "none",
    "credentials": "not_part_of_archive", "project_binding": "not_claimed"}
_PROJECT_CLAIMS = {**_CLAIMS, "project_binding": "retained_caller_association_not_native_attestation"}
_UPDATE_CLAIMS = {**_CLAIMS, "project_binding": "retained_update_association_not_native_attestation"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class SavedExecutionError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def _require(value, code, message):
    if not value:
        raise SavedExecutionError(code, message)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _digest(value):
    _require(isinstance(value, str) and _HASH.fullmatch(value), "invalid_saved_execution", "expected lowercase SHA-256")


def _fields(value, names):
    _require(isinstance(value, dict) and set(value) == set(names.split()),
             "invalid_saved_execution", "unknown or missing record fields")


def _decode(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_RECORD_BYTES,
             "archive_budget_exceeded", "expected bounded record bytes")
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "invalid_saved_execution", "duplicate JSON key")
            result[key] = value
        return result
    def constant(_value):
        raise SavedExecutionError("invalid_saved_execution", "nonfinite JSON scalar")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        pending, count = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            count += 1
            _require(depth <= 64 and count <= 2_000_000, "archive_budget_exceeded", "JSON depth/item budget exceeded")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
            elif type(item) is float:
                _require(math.isfinite(item), "invalid_saved_execution", "nonfinite JSON number")
        _require(_canonical(value).encode("utf-8") == raw, "invalid_saved_execution", "record bytes must be exact canonical UTF-8 JSON")
        return value
    except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, SavedExecutionError):
            raise
        raise SavedExecutionError("invalid_saved_execution", "malformed canonical JSON record") from exc


def _checked(raw):
    data = _decode(raw)
    try:
        project_record = isinstance(data, dict) and data.get("schema") == PROJECT_ARCHIVE_SCHEMA
        update_record = isinstance(data, dict) and data.get("schema") == UPDATE_ARCHIVE_SCHEMA
        _fields(data, "schema protocol binding source source_encoding source_byte_length source_utf16_units plan_evidence planned_units grounded_evidence claims record_digest"
                + (" project_submission" if project_record else " update_submission" if update_record else ""))
        _require(data["schema"] in (ARCHIVE_SCHEMA, PROJECT_ARCHIVE_SCHEMA, UPDATE_ARCHIVE_SCHEMA) and data["protocol"] == CONNECTOR_PROTOCOL,
                 "unsupported_saved_execution", "unsupported archive or Connector protocol schema")
        _digest(data["record_digest"])
        _require(_hash({key: value for key, value in data.items() if key != "record_digest"}) == data["record_digest"],
                 "invalid_saved_execution", "record digest mismatch")
        binding = data["binding"]
        _fields(binding, "target operation_id source_sha256 precondition")
        _fields(binding["target"], "journal_id instance_id revit_version")
        target = RuntimeTarget(**binding["target"])
        _require(target.to_dict() == binding["target"], "invalid_saved_execution", "target UUIDs must be canonical")
        _require(_uuid(binding["operation_id"], "operation_id") == binding["operation_id"],
                 "invalid_saved_execution", "operation UUID must be canonical")
        _fields(binding["precondition"], "document_key revision active_view_id selection_digest")
        precondition = ContextPrecondition(**binding["precondition"])
        _require(_canonical(precondition.to_dict()) == _canonical(binding["precondition"]),
                 "invalid_saved_execution", "precondition representation differs")
        source = data["source"]
        _require(isinstance(source, str) and bool(source.strip()) and data["source_encoding"] == "utf-8",
                 "invalid_saved_execution", "expected original UTF-8 source text")
        encoded = source.encode("utf-8")
        _digest(binding["source_sha256"])
        _require(hashlib.sha256(encoded).hexdigest() == binding["source_sha256"],
                 "invalid_saved_execution", "source SHA differs from full original source")
        units = len(source.encode("utf-16-le")) // 2
        _require(type(data["source_byte_length"]) is int and data["source_byte_length"] == len(encoded)
                 and type(data["source_utf16_units"]) is int and data["source_utf16_units"] == units,
                 "invalid_saved_execution", "source byte/UTF-16 lengths differ")
        _require(units <= MAX_SOURCE_CHARS, "archive_budget_exceeded", "source exceeds Connector UTF-16 limit")
        plan = data["plan_evidence"]
        plan_fields = "schema ir_version family intent allow_destructive bulk source_op_count program_id ops plan_digest"
        if isinstance(plan, dict) and plan.get("schema") == LINEAGED_PLAN_SCHEMA:
            plan_fields += " lineage"
        _fields(plan, plan_fields)
        _require(plan["schema"] in (PLAN_SCHEMA, LINEAGED_PLAN_SCHEMA)
                 and isinstance(plan["ops"], list) and bool(plan["ops"]),
                 "unsupported_saved_execution", "expected retained plan evidence schema")
        if plan["schema"] == LINEAGED_PLAN_SCHEMA:
            _require(type(plan["lineage"]) is str
                     and LINEAGE_FORM.fullmatch(plan["lineage"]) is not None,
                     "invalid_saved_execution", "malformed retained native lineage")
        _require(isinstance(plan["ir_version"], str) and bool(plan["ir_version"])
                 and plan["family"] in ("write", "query") and isinstance(plan["intent"], str)
                 and type(plan["allow_destructive"]) is bool and type(plan["bulk"]) is bool
                 and type(plan["source_op_count"]) is int and plan["source_op_count"] > 0
                 and (plan["program_id"] is None or isinstance(plan["program_id"], str))
                 and all(isinstance(op, dict) for op in plan["ops"]),
                 "invalid_saved_execution", "malformed plan envelope claims")
        _digest(plan["plan_digest"])
        _require(_hash({key: value for key, value in plan.items() if key != "plan_digest"}) == plan["plan_digest"],
                 "invalid_saved_execution", "retained plan evidence digest mismatch")
        _require(isinstance(data["planned_units"], list), "invalid_saved_execution", "planned units must be an array of retained claims")
        ground = data["grounded_evidence"]
        if ground is not None:
            _fields(ground, "schema plan_digest context validation ops resolutions ground_digest")
            _require(ground["schema"] == GROUND_SCHEMA and ground["plan_digest"] == plan["plan_digest"],
                     "invalid_saved_execution", "ground evidence schema or parent plan differs")
            _fields(ground["validation"], "derived_artifacts_verified selector_resolution_replayed")
            _require(isinstance(ground["context"], dict) and isinstance(ground["ops"], list)
                     and isinstance(ground["resolutions"], list)
                     and all(type(value) is bool for value in ground["validation"].values()),
                     "invalid_saved_execution", "malformed grounding envelope claims")
            _digest(ground["ground_digest"])
            _require(_hash({key: value for key, value in ground.items() if key != "ground_digest"}) == ground["ground_digest"],
                     "invalid_saved_execution", "retained ground evidence digest mismatch")
        _require(data["claims"] == (_PROJECT_CLAIMS if project_record else _UPDATE_CLAIMS if update_record else _CLAIMS), "invalid_saved_execution", "unsupported archive claims")
        if project_record:
            from kir.project_submission import validate_submission_claims
            validate_submission_claims(data["project_submission"], execution=binding,
                plan_evidence=plan, planned_units=data["planned_units"], grounded_evidence=ground, source=source)
        if update_record:
            from kir.update_submission import validate_update_submission_claims
            validate_update_submission_claims(data["update_submission"], execution=binding,
                plan_evidence=plan, planned_units=data["planned_units"])
        return data
    except SavedExecutionError:
        raise
    except (TypeError, ValueError, KeyError, UnicodeError) as exc:
        raise SavedExecutionError("invalid_saved_execution", "malformed binding or retained evidence") from exc


def _capture(prepared, *, submission=None, level_update=None):
    _require(type(prepared) is PreparedExecution, "fresh_preparation_required", "expected fresh PreparedExecution, never loaded claims")
    try:
        return _capture_json(prepared, submission=submission, level_update=level_update)
    except SavedExecutionError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise SavedExecutionError("invalid_saved_execution", "prepared input contains non-JSON or malformed retained claims") from exc


def _capture_json(prepared, *, submission=None, level_update=None):
    _require(submission is None or level_update is None, "conflicting_submission", "choose project creation OR level update association")
    data = {"schema": ARCHIVE_SCHEMA, "protocol": CONNECTOR_PROTOCOL, "binding": prepared.binding_dict(),
        "source": prepared.source, "source_encoding": "utf-8", "source_byte_length": len(prepared.source.encode("utf-8")),
        "source_utf16_units": len(prepared.source.encode("utf-16-le")) // 2,
        "plan_evidence": prepared.planned.to_evidence_dict(), "planned_units": list(prepared.planned.units),
        "grounded_evidence": prepared.grounded.to_evidence_dict() if prepared.grounded is not None else None,
        "claims": dict(_CLAIMS)}
    # Compiler units may contain immutable mappings/tuples. The existing owner
    # exposes its JSON carrier; detach it without replanning or changing scalars.
    from kir.project import _thaw
    data = _thaw(data)
    if submission is not None:
        from kir.project_submission import SubmittedProjectBinding
        _require(type(submission) is SubmittedProjectBinding, "fresh_submission_required", "expected a fresh typed SubmittedProjectBinding, not serialized claims")
        data.update(schema=PROJECT_ARCHIVE_SCHEMA, project_submission=submission.to_dict(), claims=dict(_PROJECT_CLAIMS))
    if level_update is not None:
        from kir.update_submission import SubmittedLevelUpdate
        _require(type(level_update) is SubmittedLevelUpdate, "fresh_update_submission_required", "expected a fresh update association, not stored claims")
        data.update(schema=UPDATE_ARCHIVE_SCHEMA, update_submission=level_update.to_dict(), claims=dict(_UPDATE_CLAIMS))
    data["record_digest"] = _hash(data)
    raw = _canonical(data).encode("utf-8")
    _checked(raw)
    return raw


def _path(value):
    try:
        path = Path(value).absolute()
        _require("\x00" not in str(path), "invalid_archive_path", "path contains NUL")
        return path
    except (TypeError, ValueError, OSError) as exc:
        if isinstance(exc, SavedExecutionError):
            raise
        raise SavedExecutionError("invalid_archive_path", "expected a filesystem path") from exc


def _sidecars_absent(path):
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        _require(not sidecar.exists() and not sidecar.is_symlink(), "archive_recovery_required",
                 "SQLite recovery sidecar exists; no recovery or deletion is attempted")


def _header(path):
    try:
        info = path.lstat()
        _require(stat.S_ISREG(info.st_mode), "invalid_archive_path", "archive must be a regular non-symlink file")
        _require(100 <= info.st_size <= MAX_DATABASE_BYTES, "archive_budget_exceeded", "archive file size is outside bounds")
        with path.open("rb") as stream:
            header = stream.read(100)
    except OSError as exc:
        raise SavedExecutionError("archive_unavailable", "archive cannot be read") from exc
    _require(header[:16] == b"SQLite format 3\x00" and header[18:20] == b"\x01\x01"
             and int.from_bytes(header[60:64], "big") == 1
             and int.from_bytes(header[68:72], "big") == _APPLICATION_ID,
             "invalid_archive_database", "foreign, incomplete or unsupported SQLite archive header")


def _connect(path, *, readonly):
    connection = sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                                 uri=True, timeout=5., isolation_level=None)
    try:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_RECORD_BYTES)
        connection.execute("PRAGMA trusted_schema=OFF")
        if readonly:
            connection.execute("PRAGMA query_only=ON")
        else:
            _require(connection.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",),
                     "archive_storage_failed", "SQLite DELETE journaling unavailable")
            connection.execute("PRAGMA synchronous=EXTRA")
            _require(connection.execute("PRAGMA synchronous").fetchone() == (3,),
                     "archive_storage_failed", "SQLite synchronous=EXTRA unavailable")
        return connection
    except BaseException:
        connection.close()
        raise


def _read_record(connection):
    _require(connection.execute("PRAGMA application_id").fetchone() == (_APPLICATION_ID,)
             and connection.execute("PRAGMA user_version").fetchone() == (1,),
             "invalid_archive_database", "archive database identity differs")
    schema = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema LIMIT 2").fetchall()
    _require(len(schema) == 1 and schema[0][:3] == ("table", "saved_execution", "saved_execution")
             and " ".join((schema[0][3] or "").split()) == " ".join(_TABLE_SQL.split()),
             "invalid_archive_database", "unknown/malformed archive table, index, view or trigger")
    _require(connection.execute("PRAGMA quick_check(1)").fetchall() == [("ok",)],
             "invalid_archive_database", "SQLite archive integrity check failed")
    metadata = connection.execute("SELECT singleton,typeof(payload),length(CAST(payload AS BLOB)) FROM saved_execution LIMIT 2").fetchall()
    _require(len(metadata) == 1 and metadata[0][0] == 1 and metadata[0][1] == "text",
             "invalid_archive_database", "archive requires one text record at singleton 1")
    _require(0 < metadata[0][2] <= MAX_RECORD_BYTES, "archive_budget_exceeded", "stored record exceeds byte budget")
    raw = connection.execute("SELECT payload FROM saved_execution WHERE singleton=1").fetchone()[0].encode("utf-8")
    _checked(raw)
    return raw


def _flush_created(path):
    # SQLite already committed through its platform VFS. An extra file flush
    # and POSIX directory flush cover creation metadata where Python supports it.
    # Windows _commit/FlushFileBuffers needs a write-capable handle. Opening
    # this just-created file O_RDWR neither truncates nor changes its contents.
    descriptor = os.open(path, os.O_RDWR)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@dataclass(frozen=True, slots=True, init=False)
class SavedExecutionRecord:
    digest: str
    _raw: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use create_new or load; an archive is not fresh compiler evidence")

    @classmethod
    def _from_bytes(cls, raw):
        data = _checked(raw)
        result = object.__new__(cls)
        object.__setattr__(result, "digest", data["record_digest"])
        object.__setattr__(result, "_raw", raw)
        return result

    @classmethod
    def create_new(cls, path, prepared: PreparedExecution):
        """New local file only. Any failure means no permission to dispatch."""
        return cls._create_record(path, _capture(prepared))

    @classmethod
    def create_project_new(cls, path, prepared: PreparedExecution, submission):
        """Explicit NEW /2 record; association and execution input commit together."""
        from kir.project_submission import SubmittedProjectBinding
        _require(type(submission) is SubmittedProjectBinding, "fresh_submission_required", "expected fresh typed submission association")
        return cls._create_record(path, _capture(prepared, submission=submission))

    @classmethod
    def capture_project(cls, prepared: PreparedExecution, submission):
        """Build the same immutable Archive/2 bytes for atomic ProjectStore storage.

        This method does not persist anything and cannot authorize dispatch.
        The caller must receive a new durable reservation acknowledgement.
        """
        from kir.project_submission import SubmittedProjectBinding
        _require(type(submission) is SubmittedProjectBinding, "fresh_submission_required", "fresh project association required")
        return cls._from_bytes(_capture(prepared, submission=submission))

    @classmethod
    def create_update_new(cls, path, prepared: PreparedExecution, submission):
        """Explicit NEW /3 record; reuse the same immutable SQLite writer."""
        from kir.update_submission import SubmittedLevelUpdate
        _require(type(submission) is SubmittedLevelUpdate, "fresh_update_submission_required", "fresh typed update association required")
        return cls._create_record(path, _capture(prepared, level_update=submission))

    @classmethod
    def _create_record(cls, path, raw):
        # Both logical payload versions share this exact immutable container.
        path = _path(path)
        _sidecars_absent(path)
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        except FileExistsError as exc:
            raise SavedExecutionError("archive_exists", "existing archive path is never adopted or overwritten") from exc
        except OSError as exc:
            raise SavedExecutionError("archive_storage_failed", "cannot exclusively create archive path") from exc
        connection, committed = None, False
        try:
            connection = _connect(path, readonly=False)
            connection.execute("BEGIN IMMEDIATE")
            _require(not connection.execute("SELECT name FROM sqlite_schema").fetchall()
                     and connection.execute("PRAGMA application_id").fetchone() == (0,)
                     and connection.execute("PRAGMA user_version").fetchone() == (0,),
                     "invalid_archive_database", "new path was initialized by another writer")
            connection.execute(_TABLE_SQL)
            connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            connection.execute("PRAGMA user_version=1")
            connection.execute("INSERT INTO saved_execution VALUES (1, ?)", (raw.decode("utf-8"),))
            _require(_read_record(connection) == raw, "invalid_archive_database", "inserted payload differs")
            connection.execute("COMMIT")
            committed = True
            connection.close()
            connection = None
            _flush_created(path)
            result = cls.load(path)
            _require(result._raw == raw, "invalid_archive_database", "archive changed after creation")
            return result
        except BaseException as exc:
            uncertain = committed or (connection is not None and not connection.in_transaction)
            if connection is not None and connection.in_transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    uncertain = True
            if isinstance(exc, (OSError, sqlite3.Error, SavedExecutionError)):
                raise SavedExecutionError("archive_durability_unconfirmed" if uncertain else "archive_storage_failed",
                    "initialization failed; retain file/sidecars for inspection and do not dispatch") from exc
            raise
        finally:
            if connection is not None:
                connection.close()

    @classmethod
    def load(cls, path):
        path = _path(path)
        _sidecars_absent(path)
        _header(path)
        connection = None
        try:
            connection = _connect(path, readonly=True)
            connection.execute("BEGIN")
            raw = _read_record(connection)
            _sidecars_absent(path)
            return cls._from_bytes(raw)
        except (sqlite3.Error, UnicodeError) as exc:
            raise SavedExecutionError("archive_unavailable", "read-only archive validation failed; no recovery attempted") from exc
        finally:
            if connection is not None:
                connection.close()

    def to_dict(self):
        return json.loads(self._raw)

    def binding_dict(self):
        return self.to_dict()["binding"]

    @property
    def project_submission(self):
        """Detached retained claims, NEVER a fresh SubmittedProjectBinding."""
        return self.to_dict().get("project_submission")

    @property
    def update_submission(self):
        """Detached retained baseline/association, never a fresh update plan."""
        return self.to_dict().get("update_submission")

    def require_matches(self, fresh: PreparedExecution, *, submission=None, level_update=None):
        schema = self.to_dict()["schema"]
        if schema == UPDATE_ARCHIVE_SCHEMA:
            from kir.update_submission import SubmittedLevelUpdate
            _require(type(level_update) is SubmittedLevelUpdate and submission is None,
                     "fresh_update_submission_required", "archive /3 requires its exact fresh update association")
        elif schema == PROJECT_ARCHIVE_SCHEMA:
            from kir.project_submission import SubmittedProjectBinding
            _require(type(submission) is SubmittedProjectBinding and level_update is None, "fresh_submission_required", "archive /2 requires its exact fresh submitted-project association")
        else:
            _require(submission is None and level_update is None, "submission_not_archived", "archive /1 cannot attest an unrecorded association")
        _require(_capture(fresh, submission=submission, level_update=level_update) == self._raw, "saved_execution_mismatch",
                 "fresh source, binding, plan/units, grounded evidence or project association differs from the archived input")

    def receipt_request(self, credentials: SessionCredentials, *, request_id: str):
        binding = self.binding_dict()
        _require(type(credentials) is SessionCredentials and credentials.target.to_dict() == binding["target"],
                 "target_mismatch", "same-target lookup requires credentials for the original target")
        return _request(credentials, request_id, "receipt", 30000, operation_id=binding["operation_id"])

    def cancel_before_start_request(self, credentials: SessionCredentials, *, request_id: str,
                                    timeout_ms: int = 30000):
        """Prepare explicit own-journal cancellation, never execute saved source.

        This is a control-plane write request, not a read-only receipt lookup.
        It may establish a durable no-start tombstone; started work cannot be
        interrupted or labelled rolled back. The response must still be bound
        and assessed before any local pending operation can be resolved.
        """
        binding = self.binding_dict()
        _require(type(credentials) is SessionCredentials and credentials.target.to_dict() == binding["target"],
                 "target_mismatch", "cancellation requires the original owned runtime; recovery B is read-only")
        return _request(credentials, request_id, "cancel_before_start", timeout_ms,
                        operation_id=binding["operation_id"], source_sha256=binding["source_sha256"],
                        precondition=binding["precondition"])

    def recovery_request(self, credentials: SessionCredentials, *, request_id: str):
        binding = self.binding_dict()
        return _request(credentials, request_id, "recover_receipt", 30000,
                        operation_id=binding["operation_id"], recovery_target=binding["target"])
