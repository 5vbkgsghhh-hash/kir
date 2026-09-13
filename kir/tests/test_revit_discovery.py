"""Actual per-session directory layout; no connection or liveness simulation."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest

from kir.revit_connector import RuntimeTarget
from kir.revit_discovery import DiscoveryError, load_discovery, scan_discovery


NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


def record(version="2023", **changes):
    return {"protocol": "kir-revit-connector/4", "target": {"journal_id": str(uuid4()),
            "instance_id": str(uuid4()), "revit_version": version}, "session_id": str(uuid4()),
            "pipe_name": "kir-revit-123-" + "a" * 24, "token": "sensitive-session-token",
            "process_id": 123, "expires_utc": "2026-09-05T12:10:00.0000000Z", **changes}


def raw(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def write(root, value, *, instance=None, session=None):
    folder = root / (instance or value["target"]["instance_id"])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ((session or value["session_id"]) + ".json")
    path.write_bytes(raw(value))
    return path


def test_two_simultaneous_revit_years_are_explicitly_selected_and_not_called_live(tmp_path):
    a, b = record(), record("2026")
    write(tmp_path, a)
    write(tmp_path, b)
    catalog = scan_discovery(tmp_path)
    assert len(catalog.advertisements) == 2 and catalog.issues == ()
    selected = catalog.select(target=RuntimeTarget(**b["target"]), session_id=b["session_id"], now=NOW)
    assert selected.credentials.target.revit_version == "2026"
    assert selected.credentials.token == b["token"]
    summary = selected.summary(now=NOW)
    assert summary["liveness"] == "not_probed" and summary["authority"] == "unverified_advertisement"
    assert b["token"] not in repr(selected) and b["token"] not in repr(catalog)
    assert b["token"] not in json.dumps(summary)
    summary["target"]["journal_id"] = "forged"
    assert selected.credentials.target.journal_id == b["target"]["journal_id"]
    with pytest.raises(FrozenInstanceError):
        selected.pipe_name = "wrong"


def test_session_rotation_requires_explicit_session_not_latest_timestamp(tmp_path):
    a = record()
    b = {**a, "session_id": str(uuid4()), "token": "new-secret", "expires_utc": "2026-09-05T12:20:00.0000000Z"}
    write(tmp_path, a)
    write(tmp_path, b)
    catalog = scan_discovery(tmp_path)
    assert len(catalog.advertisements) == 2
    target = RuntimeTarget(**a["target"])
    assert catalog.select(target=target, session_id=a["session_id"], now=NOW).credentials.token == a["token"]
    assert catalog.select(target=target, session_id=b["session_id"], now=NOW).credentials.token == b["token"]
    with pytest.raises(DiscoveryError, match="selection_not_unique"):
        catalog.select(target=replace(target, journal_id=str(uuid4())), session_id=a["session_id"], now=NOW)


def test_expired_file_is_reported_preserved_and_not_selected(tmp_path):
    value = record(expires_utc="2026-09-05T11:59:59.9999999Z")
    path = write(tmp_path, value)
    before = path.read_bytes()
    catalog = scan_discovery(tmp_path)
    assert len(catalog.advertisements) == 1 and catalog.issues == ()
    assert catalog.advertisements[0].summary(now=NOW)["advertised_unexpired"] is False
    with pytest.raises(DiscoveryError, match="advertisement_expired"):
        catalog.select(target=RuntimeTarget(**value["target"]), session_id=value["session_id"], now=NOW)
    assert path.read_bytes() == before


def test_dotnet_seventh_fraction_digit_is_not_lost_to_python_microseconds():
    exact = load_discovery(raw(record(expires_utc="2026-09-05T12:00:00.0000000Z")))
    later_tick = load_discovery(raw(record(expires_utc="2026-09-05T12:00:00.0000001Z")))
    assert not exact.advertised_unexpired(now=NOW)
    assert later_tick.advertised_unexpired(now=NOW)
    assert not later_tick.advertised_unexpired(now=NOW + timedelta(microseconds=1))
    assert later_tick.advertised_unexpired(now=NOW.astimezone(timezone(timedelta(hours=3))))
    with pytest.raises(DiscoveryError, match="invalid_clock"):
        exact.advertised_unexpired(now=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("timestamp", ["2026-09-05T12:10:00.٠٠٠٠٠٠١Z", "٢٠٢٦-09-05T12:10:00.0000001Z"])
def test_invariant_dotnet_timestamp_does_not_accept_unicode_digit_lookalikes(timestamp):
    with pytest.raises(DiscoveryError):
        load_discovery(raw(record(expires_utc=timestamp)))


@pytest.mark.parametrize("field,value", [("protocol", "kir-revit-connector/3"), ("process_id", True),
    ("process_id", 0), ("process_id", 1 << 31), ("token", ""), ("token", "\ud800"),
    ("pipe_name", "../other"), ("pipe_name", "\\\\remote\\pipe\\p"),
    ("expires_utc", "2026-09-05T12:10:00Z"), ("expires_utc", "2026-09-05T12:10:00.0000000+03:00"),
    ("expires_utc", "2026-02-30T12:10:00.0000000Z"), ("session_id", "0" * 32)])
def test_invalid_complete_record_fields_are_named_refusals_without_echoing_secret(field, value):
    value = record(**{field: value})
    encoded = json.dumps(value).encode()
    with pytest.raises(DiscoveryError) as error:
        load_discovery(encoded)
    assert "sensitive-session-token" not in str(error.value)


def test_known_duplicate_and_escaped_duplicate_rejected_even_if_last_wins_is_valid():
    value = record()
    encoded = json.dumps(value)
    for name in ('"token"', '"\\u0074oken"'):
        duplicate = encoded.replace('"token":', f'{name}: "ignored", "token":')
        assert json.loads(duplicate) == value
        with pytest.raises(DiscoveryError, match="duplicate"):
            load_discovery(duplicate.encode())


@pytest.mark.parametrize("mutation", ["extra", "target_extra", "upper_uuid", "zero_uuid", "year_number"])
def test_binding_schema_is_closed_and_canonical(mutation):
    value = record()
    if mutation == "extra": value["native_execution"] = "verified"
    elif mutation == "target_extra": value["target"]["extra"] = 1
    elif mutation == "upper_uuid": value["target"]["instance_id"] = value["target"]["instance_id"].upper()
    elif mutation == "zero_uuid": value["target"]["journal_id"] = "00000000-0000-0000-0000-000000000000"
    else: value["target"]["revit_version"] = 2023
    with pytest.raises(DiscoveryError):
        load_discovery(raw(value))


def test_bad_neighbor_wrong_container_and_torn_file_do_not_hide_valid_runtime(tmp_path):
    valid = record()
    write(tmp_path, valid)
    wrong = record("2026")
    path = write(tmp_path, wrong, instance=str(uuid4()))
    torn = record()
    torn_path = write(tmp_path, torn)
    torn_path.write_bytes(b'{"token":"secret-prefix')
    before = path.read_bytes(), torn_path.read_bytes()
    catalog = scan_discovery(tmp_path)
    assert len(catalog.advertisements) == 1
    assert {issue.code for issue in catalog.issues} == {"discovery_path_mismatch", "invalid_discovery"}
    assert (path.read_bytes(), torn_path.read_bytes()) == before
    assert "secret-prefix" not in repr(catalog)


def test_ordinary_symlinks_are_not_followed_and_legacy_root_is_not_reinterpreted(tmp_path):
    discovery = tmp_path / "discovery"
    discovery.mkdir()
    value = record()
    outside = tmp_path / "outside.json"
    outside.write_bytes(raw(value))
    folder = discovery / value["target"]["instance_id"]
    folder.mkdir()
    (folder / (value["session_id"] + ".json")).symlink_to(outside)
    (discovery / str(uuid4())).symlink_to(tmp_path, target_is_directory=True)
    (discovery / "connector.json").write_bytes(b'{"legacy":true}')
    catalog = scan_discovery(discovery)
    assert catalog.advertisements == () and len(catalog.issues) == 3
    assert outside.read_bytes() == raw(value)
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(discovery, target_is_directory=True)
    with pytest.raises(DiscoveryError, match="invalid_discovery_directory"):
        scan_discovery(linked_root)


def test_scan_budget_does_not_return_an_incomplete_catalog_as_complete(tmp_path, monkeypatch):
    import kir.revit_discovery as discovery
    for _ in range(2):
        write(tmp_path, record())
    monkeypatch.setattr(discovery, "MAX_DISCOVERY_ENTRIES", 2)
    with pytest.raises(DiscoveryError, match="scan_budget_exceeded"):
        scan_discovery(tmp_path)


def test_missing_directory_and_oversize_file_are_not_called_no_live_revit(tmp_path):
    with pytest.raises(DiscoveryError, match="discovery_unavailable"):
        scan_discovery(tmp_path / "missing")
    with pytest.raises(DiscoveryError):
        load_discovery(b" " * (64 * 1024 + 1))
