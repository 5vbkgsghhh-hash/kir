"""Real SQLite SQL/readback for Archive3; no file durability claim."""
import sqlite3

import pytest

from kir import saved_execution as archive
from kir.tests.test_update_submission_memory import record_values


def database():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute(f"PRAGMA application_id={archive._APPLICATION_ID}")
    connection.execute("PRAGMA user_version=1")
    connection.execute(archive._TABLE_SQL)
    return connection


def test_archive3_commit_and_sql_readback_preserve_exact_checked_payload():
    _, _, record = record_values()
    connection = database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO saved_execution VALUES (1, ?)", (record._raw.decode(),))
        connection.execute("COMMIT")
        raw = archive._read_record(connection)
        loaded = archive.SavedExecutionRecord._from_bytes(raw)
        assert raw == record._raw and loaded.digest == record.digest
        assert loaded.update_submission == record.update_submission
        connection.execute("PRAGMA query_only=ON")
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("UPDATE saved_execution SET payload='changed'")
    finally:
        connection.close()


def test_rolled_back_insert_never_becomes_an_available_archive():
    _, _, record = record_values()
    connection = database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO saved_execution VALUES (1, ?)", (record._raw.decode(),))
        connection.execute("ROLLBACK")
        with pytest.raises(archive.SavedExecutionError):
            archive._read_record(connection)
    finally:
        connection.close()


@pytest.mark.parametrize("fault", ["application_id", "version", "extra_table", "blob"])
def test_sql_container_corruption_is_not_a_valid_update_record(fault):
    _, _, record = record_values()
    connection = database()
    try:
        payload = sqlite3.Binary(record._raw) if fault == "blob" else record._raw.decode()
        connection.execute("INSERT INTO saved_execution VALUES (1, ?)", (payload,))
        if fault == "application_id": connection.execute("PRAGMA application_id=123")
        if fault == "version": connection.execute("PRAGMA user_version=2")
        if fault == "extra_table": connection.execute("CREATE TABLE extra(value TEXT)")
        with pytest.raises(archive.SavedExecutionError):
            archive._read_record(connection)
    finally:
        connection.close()
