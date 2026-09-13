"""Read-only per-session discovery; advertisements are NOT live connections.

No implicit newest/first runtime selection, PID liveness test, stale-file
deletion, pipe connection, document capture or replay occurs. The native response
must still be authenticated and match the selected target/session. A local file
and its unexpired timestamp cannot confer that evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from kir.revit_connector import CONNECTOR_PROTOCOL, RuntimeTarget, SessionCredentials, _uuid


MAX_DISCOVERY_BYTES = 64 * 1024
MAX_DISCOVERY_ENTRIES = 1024
_EXPIRY = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(\d{7})Z\Z", re.ASCII)


class DiscoveryError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _require(condition, code, message):
    if not condition:
        raise DiscoveryError(code, message)


def _canonical_uuid(value, name):
    canonical = _uuid(value, name)
    _require(canonical == value, "invalid_discovery", f"{name} is not canonical")
    return canonical


def _ticks(value: datetime) -> int:
    _require(type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None,
             "invalid_clock", "an explicit timezone-aware datetime is required")
    delta = value.astimezone(timezone.utc) - datetime(1, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 10_000_000 + delta.microseconds * 10


@dataclass(frozen=True, slots=True)
class DiscoveryAdvertisement:
    credentials: SessionCredentials = field(repr=False)
    pipe_name: str
    process_id: int
    expires_utc: str
    source_sha256: str
    _expiry_ticks: int = field(repr=False)

    def advertised_unexpired(self, *, now: datetime) -> bool:
        return _ticks(now) < self._expiry_ticks

    def summary(self, *, now: datetime) -> dict:
        """Detached diagnostics deliberately omit token and raw file contents."""
        return {"target": self.credentials.target.to_dict(), "session_id": self.credentials.session_id,
                "pipe_name": self.pipe_name, "process_id": self.process_id,
                "expires_utc": self.expires_utc, "source_sha256": self.source_sha256,
                "advertised_unexpired": self.advertised_unexpired(now=now),
                "liveness": "not_probed", "authority": "unverified_advertisement"}


def load_discovery(raw: bytes) -> DiscoveryAdvertisement:
    """Strict inert parser for the actual App/4 discovery format, including .NET ticks."""
    try:
        _require(type(raw) is bytes and len(raw) <= MAX_DISCOVERY_BYTES,
                 "invalid_discovery", "expected bounded UTF-8 bytes")
        def pairs(items):
            result = {}
            for key, value in items:
                _require(key not in result, "invalid_discovery", "duplicate JSON key")
                result[key] = value
            return result
        def constant(_):
            raise DiscoveryError("invalid_discovery", "non-finite JSON scalar")
        data = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs, parse_constant=constant)
        _require(isinstance(data, dict) and set(data) == {
            "protocol", "target", "session_id", "pipe_name", "token", "process_id", "expires_utc"},
            "invalid_discovery", "unsupported discovery fields")
        _require(data["protocol"] == CONNECTOR_PROTOCOL, "unsupported_protocol", "discovery protocol differs")
        target_data = data["target"]
        _require(isinstance(target_data, dict) and set(target_data) == {"journal_id", "instance_id", "revit_version"},
                 "invalid_discovery", "unsupported target fields")
        for key in ("journal_id", "instance_id"):
            _canonical_uuid(target_data[key], key)
        target = RuntimeTarget(**target_data)
        credentials = SessionCredentials(target, _canonical_uuid(data["session_id"], "session_id"), data["token"])
        pid, pipe, expires = data["process_id"], data["pipe_name"], data["expires_utc"]
        _require(type(pid) is int and 0 < pid <= (1 << 31) - 1,
                 "invalid_discovery", "process_id must be a positive Int32")
        _require(isinstance(pipe, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", pipe) is not None,
                 "invalid_discovery", "unsupported local pipe name")
        match = _EXPIRY.fullmatch(expires) if isinstance(expires, str) else None
        _require(match is not None, "invalid_discovery", "expected App UTC timestamp with seven fractional digits")
        second = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        expiry_ticks = _ticks(second) + int(match[2])
        return DiscoveryAdvertisement(credentials, pipe, pid, expires, hashlib.sha256(raw).hexdigest(), expiry_ticks)
    except DiscoveryError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        # Do not interpolate untrusted payloads/tokens into ordinary diagnostics.
        raise DiscoveryError("invalid_discovery", "malformed discovery value") from error


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    relative_path: str
    code: str


@dataclass(frozen=True, slots=True)
class DiscoveryCatalog:
    advertisements: tuple[DiscoveryAdvertisement, ...]
    issues: tuple[DiscoveryIssue, ...]

    def select(self, *, target: RuntimeTarget, session_id: str, now: datetime) -> DiscoveryAdvertisement:
        """Require an exact explicit target AND session; never choose first/newest."""
        _require(type(target) is RuntimeTarget, "invalid_selection", "exact RuntimeTarget required")
        _canonical_uuid(session_id, "session_id")
        matches = [record for record in self.advertisements
                   if record.credentials.target == target and record.credentials.session_id == session_id]
        _require(len(matches) == 1, "selection_not_unique", "selected advertisement is absent or ambiguous")
        _require(matches[0].advertised_unexpired(now=now), "advertisement_expired", "selected session advertisement has expired")
        return matches[0]


def scan_discovery(discovery_dir: str | os.PathLike[str]) -> DiscoveryCatalog:
    """Read only an explicitly chosen v4/discovery directory, never a legacy root.

    Complete files are read once with a byte budget; stale entries remain on
    disk. Ordinary symlinks and non-regular files are not followed. This is not
    a hostile-filesystem sandbox or proof of Windows ACLs. Concurrent file
    disappearance is a per-entry diagnostic, not an empty/live verdict.
    """
    root = Path(discovery_dir)
    _require(not root.is_symlink(), "invalid_discovery_directory", "discovery directory cannot be a symlink")
    records, issues, visited = [], [], 0

    def entries(path):
        nonlocal visited
        try:
            with os.scandir(path) as iterator:
                rows = []
                for entry in iterator:
                    visited += 1
                    _require(visited <= MAX_DISCOVERY_ENTRIES, "scan_budget_exceeded", "discovery entry budget exceeded; catalog is not complete")
                    rows.append(entry)
                return sorted(rows, key=lambda entry: entry.name)
        except OSError as error:
            raise DiscoveryError("discovery_unavailable", "cannot enumerate the chosen directory") from error

    for instance in entries(root):
        try:
            _canonical_uuid(instance.name, "instance directory")
            _require(instance.is_dir(follow_symlinks=False), "non_directory_entry", "expected instance directory")
            files = entries(instance.path)
        except DiscoveryError as error:
            if error.code == "scan_budget_exceeded":
                raise
            issues.append(DiscoveryIssue(instance.name, error.code))
            continue
        except (ValueError, OSError):
            issues.append(DiscoveryIssue(instance.name, "invalid_instance_entry"))
            continue
        for entry in files:
            path = instance.name + "/" + entry.name
            try:
                _require(entry.name.endswith(".json"), "non_session_entry", "not a session JSON file")
                session = _canonical_uuid(entry.name[:-5], "session filename")
                _require(entry.is_file(follow_symlinks=False), "non_regular_entry", "not a regular file")
                with open(entry.path, "rb") as stream:
                    record = load_discovery(stream.read(MAX_DISCOVERY_BYTES + 1))
                _require(record.credentials.target.instance_id == instance.name and record.credentials.session_id == session,
                         "discovery_path_mismatch", "record target/session differs from its container")
                records.append(record)
            except DiscoveryError as error:
                issues.append(DiscoveryIssue(path, error.code))
            except (ValueError, OSError):
                issues.append(DiscoveryIssue(path, "unreadable_session_entry"))
    return DiscoveryCatalog(tuple(records), tuple(issues))


__all__ = ["DiscoveryError", "DiscoveryAdvertisement", "DiscoveryIssue", "DiscoveryCatalog",
           "load_discovery", "scan_discovery"]
