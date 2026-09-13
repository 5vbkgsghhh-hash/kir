"""Durable, single-project local history with an interprocess head CAS.

This owner is distinct from existing stores: decompile.graph_store persists an
observed graph per extraction; decompile.journal_store locks and persists the
reverse compiler's Merkle history by document name; live.journal_store records
execution/program events fail-open; operations.store owns dispatch receipts.
None owns ProjectRevision's authored snapshots and expected-head acceptance.
We reuse ProjectRevision.loads/dumps as the payload contract, not those formats.

SQLite serializes writers with BEGIN IMMEDIATE. A new snapshot and head advance
commit together; exact redelivery returns the *current* head without rewinding.
Drafts are legal. This module never evaluates a recipe, plans, or publishes BIM.

Creation defaults to schema /1. Explicit schema /2 adds content-addressed
geometry bundles in this SAME SQLite owner: required new assets, revision and
head CAS commit together. upgrade_schema changes only storage structure, never
old authored payloads or their hashes. Body references must resolve and match
their declared address/source context; inert validation does not prove saved
preview/body equivalence. Only explicit materialization runs the native kernel.

Explicit schema /3 retains /2 and adds scoped Level update reservations and
accepted field-evidence checkpoints. Their CAS never moves the authored head;
stored claims are not reconstructed as fresh observations or write authority.
Explicit schema /4 additionally retains bound native not_started resolutions;
they clear only the matching pending input, without advancing either head.
Explicit migrations to /4 and later use the guarded FK-off migration transaction;
this permits /3's table rebuild, followed by a foreign-key check before commit.
Schema /5 adds authored task events and heads. Candidates remain outside linear
revisions until decision; their retained assets share the same geometry owner.
Schema /6 adds immutable CREATE inputs and native-namespace output reservations.
Input reservation is not dispatch or retry permission; receipt qualification
does not belong to this initial reservation/read API.
Schema /7 retains these rows and adds linked no-start resolutions. Only explicit
release of a validated no-start input removes its output owners; its UUID/input
remain reserved, and historical lookup never recreates dispatch permission.

Local-filesystem durability uses rollback DELETE journaling, synchronous=EXTRA,
and directory fsync on POSIX creation. It relies on SQLite/VFS, working locks,
and honest filesystem/device flushes, not network filesystem semantics. Process
crash tests are not physical power-loss tests. Read-only access will not perform
hot-journal recovery: explicit writable open may be needed after a crash.

Hot paths validate schema, ownership, head and the addressed payload, not every
old snapshot. history() separately verifies the complete chain and SQLite file
integrity. Untouched historical corruption may therefore remain undiscovered
until accessed/audited.

What this rule means for GEOMETRY ASSETS, and why it is written down as a
number (07.09.2026). Before this fix the code did not follow the rule:
`_read_state` walked ALL of the head's assets on EVERY transaction, and the
cost grew as `(N+2)·M` — at 705 bodies exactly 499,140 reads (checked against
the profile down to the unit), 74% of analysis time, while the model
`T = 7.984e-5·N² + 3.124e-2·N` (fitted on 205 and 2005 bodies, predicted 705
with a 2.3% error) promised ~2.3 hours at 10,000 bodies. Now:
  * READING (`open`, `head`, `get`, `get_asset`) checks the schema, the
    store's identity, the head's payload BYTE-FOR-BYTE, and — in `get_asset`
    — the ADDRESSED asset in full (bytes plus parsing and an owner check).
    The remaining `M-1` head assets are NOT READ on this path.
  * WRITING (`create`, `commit`, `upgrade_schema`) still walks all of the
    head's assets: you cannot write over a head whose bodies have drifted
    apart.
  * A FULL WALK is reachable through the existing name `history()` — it
    checks every revision of the chain together with its assets. No new
    public names are introduced.
The consequence is stated outright, both halves. (1) The loss or corruption of
an asset that this call did NOT touch will not be discovered on the read
path — it is caught by `history()` and by any write. The loss of the
ADDRESSED body declared by the head is still `StoreCorrupt`, not
`StoreNotFound`: the read queries the revision's reference memory, not all M
rows. (2) `validate_geometry_bindings` (a body belongs to EXACTLY the output
that declared it) is also not run on the read path; for `get_asset` the
question is asked by DIGEST, and it is answered by checking the digest and
the project_id inside `_read_asset`. The full ownership check remains in
three places, and all three are mandatory until BIM appears: `history()`, any
WRITE, and `geometry_materialization.materialize_project`, through which the
entire analysis passes. No path to geometry silently bypasses it. No pruning, branch heads, external-writer support
or authentication is provided. Hashes detect inconsistency, not malicious forgery.
Never delete a SQLite journal to 'repair' this store; retain failed creation
artifacts for inspection instead of automatically overwriting or deleting them.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import sqlite3
from functools import lru_cache
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterator, TYPE_CHECKING

from kir.project import PROJECT_SCHEMA, PROJECT_SCHEMA_V2, ProjectError, ProjectRevision

if TYPE_CHECKING:
    from kir.occt_geometry import GeometryBundle


STORE_SCHEMA = "kir-project-store/1"
GEOMETRY_STORE_SCHEMA = "kir-project-store/2"
REALIZATION_STORE_SCHEMA = "kir-project-store/3"
RESOLUTION_STORE_SCHEMA = "kir-project-store/4"
TASK_STORE_SCHEMA = "kir-project-store/5"
CREATE_STORE_SCHEMA = "kir-project-store/6"
CREATE_RESOLUTION_STORE_SCHEMA = "kir-project-store/7"
STAGED_CREATE_STORE_SCHEMA = "kir-project-store/8"
_APPLICATION_ID = 0x4B495250  # KIRP, identifying this SQLite file format.
_SCHEMAS = {STORE_SCHEMA: 1, GEOMETRY_STORE_SCHEMA: 2, REALIZATION_STORE_SCHEMA: 3,
            RESOLUTION_STORE_SCHEMA: 4, TASK_STORE_SCHEMA: 5, CREATE_STORE_SCHEMA: 6, CREATE_RESOLUTION_STORE_SCHEMA: 7,
            STAGED_CREATE_STORE_SCHEMA: 8}
_CREATE_RESOLUTION_SCHEMAS = frozenset({CREATE_RESOLUTION_STORE_SCHEMA, STAGED_CREATE_STORE_SCHEMA})
_CREATE_SCHEMAS = frozenset({CREATE_STORE_SCHEMA, *_CREATE_RESOLUTION_SCHEMAS})
_TASK_SCHEMAS = frozenset({TASK_STORE_SCHEMA, *_CREATE_SCHEMAS})
_RESOLUTION_SCHEMAS = frozenset({RESOLUTION_STORE_SCHEMA, *_TASK_SCHEMAS})
_REALIZATION_SCHEMAS = frozenset({REALIZATION_STORE_SCHEMA, *_RESOLUTION_SCHEMAS})
_ASSET_SCHEMAS = frozenset({GEOMETRY_STORE_SCHEMA, *_REALIZATION_SCHEMAS})
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")

_REVISIONS_SQL = """CREATE TABLE revisions (
    sequence INTEGER PRIMARY KEY CHECK (sequence >= 0),
    revision_id TEXT NOT NULL UNIQUE CHECK (length(revision_id) = 64),
    project_id TEXT NOT NULL,
    parent_revision TEXT REFERENCES revisions(revision_id),
    payload TEXT NOT NULL
)"""
_STORE_SQL = """CREATE TABLE project_store (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version TEXT NOT NULL,
    store_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL,
    head_revision TEXT NOT NULL REFERENCES revisions(revision_id)
)"""
_ASSETS_SQL = """CREATE TABLE geometry_assets (
    digest TEXT NOT NULL PRIMARY KEY CHECK (length(digest) = 64),
    payload TEXT NOT NULL
)"""


class ProjectStoreError(RuntimeError):
    """Storage failed; no semantic/native success is implied."""


class StoreNotFound(ProjectStoreError):
    """The explicitly requested database or revision does not exist."""


class StoreExists(ProjectStoreError):
    """Creation refuses every existing path, including an empty file."""


class StoreCorrupt(ProjectStoreError):
    """Wrong schema/identity or inconsistent stored history; never reinitialize."""


class StoreConflict(ProjectStoreError):
    """The proposal is not based on the required project/parent/head."""


class StoreBusy(ProjectStoreError):
    """SQLite could not acquire a lock within the supplied timeout."""


class StoreReadOnly(ProjectStoreError):
    """A mutation was requested from an explicitly read-only handle."""


class StoreRecoveryRequired(ProjectStoreError):
    """Read-only access cannot recover a SQLite hot rollback journal."""


class StoreCommitUnknown(ProjectStoreError):
    """Commit acknowledgement failed; inspect/retry the same revision identity."""


class StoreUpgradeRequired(ProjectStoreError):
    """The requested feature needs an explicit storage-schema upgrade."""


class StoreAssetMissing(ProjectStoreError):
    """A proposed revision references a geometry asset that was not supplied."""


@dataclass(frozen=True, slots=True)
class CommitResult:
    revision_id: str
    head_revision: str
    inserted: bool


@dataclass(frozen=True, slots=True)
class _State:
    project_id: str
    store_id: str
    head: ProjectRevision
    head_sequence: int
    schema: str
    #: A guarantee of ONE handle, the same kind `_read_state` has. It travels
    #: in the state so that `_find_revision` (and through it the whole task
    #: journal) does not parse ONE AND THE SAME revision again on every
    #: transaction. What is saved is PARSING, not READING: the row always
    #: comes from SQLite, and the snapshot is handed out only when the WHOLE
    #: row matches (see `_decode_row`).
    verified: dict | None = None


def _timeout(value: float) -> float:
    if (type(value) not in (int, float) or not 0 <= value <= 30
            or not math.isfinite(value)):
        raise ProjectStoreError("timeout must be a finite number between 0 and 30 seconds")
    return float(value)


def _path(value: str | os.PathLike[str]) -> Path:
    try:
        # as_uri below quotes '?' and '#' rather than accepting caller-supplied
        # URI options. Symlinks are caller-selected paths, not a security sandbox.
        path = Path(value).absolute()
        if "\x00" in str(path):
            raise ValueError("path contains a NUL byte")
        return path
    except (TypeError, ValueError, OSError) as exc:
        raise ProjectStoreError(f"invalid database path: {exc}") from exc


def _sqlite_error(exc: sqlite3.Error) -> ProjectStoreError:
    code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return StoreBusy(f"project store is busy: {exc}")
    if code == sqlite3.SQLITE_READONLY:
        return StoreRecoveryRequired(
            "SQLite requires writable recovery or storage permissions; "
            "explicitly open(readonly=False) to recover, never delete its journal: "
            f"{exc}")
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
        return StoreCorrupt(f"invalid/corrupt SQLite project store: {exc}")
    return ProjectStoreError(f"SQLite project store failed: {exc}")


def _check_file_header(path: Path) -> None:
    """Classify before SQLite can recover a foreign hot journal on rw open.

    SQLite's stable file header specifies big-endian user_version at byte 60,
    application_id at 68, and rollback/WAL versions at 18/19:
    https://www.sqlite.org/fileformat.html#the_database_header
    This is only a conservative preflight, not schema validation or protection
    from a malicious path replacement between filesystem and SQLite reads.
    """
    try:
        with path.open("rb") as handle:
            header = handle.read(100)
    except OSError as exc:
        raise ProjectStoreError(f"cannot read project store header: {exc}") from exc
    if (len(header) != 100 or header[:16] != b"SQLite format 3\x00"
            or header[18:20] != b"\x01\x01"
            or int.from_bytes(header[60:64], "big") not in _SCHEMAS.values()
            or int.from_bytes(header[68:72], "big") != _APPLICATION_ID):
        raise StoreCorrupt("foreign/unsupported SQLite project store header; no recovery attempted")


def _connect(path: Path, *, readonly: bool, timeout: float,
             initializing: bool = False) -> sqlite3.Connection:
    try:
        if not path.exists():
            raise StoreNotFound(f"project store does not exist: {path}")
        if not path.is_file():
            raise ProjectStoreError(f"project store path is not a regular file: {path}")
    except OSError as exc:
        raise ProjectStoreError(f"cannot access project store: {exc}") from exc
    if not initializing:
        _check_file_header(path)
    connection = None
    try:
        connection = sqlite3.connect(
            path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
            uri=True, timeout=timeout, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        if readonly:
            connection.execute("PRAGMA query_only=ON")
        else:
            connection.execute("PRAGMA synchronous=EXTRA")
            if connection.execute("PRAGMA synchronous").fetchone() != (3,):
                raise ProjectStoreError("SQLite did not enable synchronous=EXTRA")
        return connection
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise _sqlite_error(exc) from exc
    except BaseException:
        if connection is not None:
            connection.close()
        raise


@lru_cache(maxsize=512)
def _normalized_sql(sql: str) -> str:
    """SQL whitespace -> one form. A pure function of the STRING, so it is cacheable.

    The schema check is read from `sqlite_schema` on EVERY transaction (that
    is the check itself), but the same handful of strings get normalized
    each time. Measurement 07.09.2026: analyzing 2000 bodies opens 2000
    transactions through `get_asset`, and `_read_state` normalized about 10
    strings for each. Caching by string weakens nothing: a different schema
    is a different string is a different answer.
    """
    return " ".join(sql.split())


_ROW = "sequence, revision_id, project_id, parent_revision, payload"


def _provided_assets(assets) -> dict:
    """Detach and revalidate input bytes before entering a write transaction."""
    if not isinstance(assets, (tuple, list)):
        raise ProjectStoreError("assets must be a list or tuple of GeometryBundle values")
    if not assets:
        return {}
    from kir.occt_geometry import GeometryBundle, GeometryRefusal

    provided = {}
    for asset in assets:
        if not isinstance(asset, GeometryBundle):
            raise ProjectStoreError("assets must contain GeometryBundle values")
        try:
            payload = asset.dumps()
            decoded = GeometryBundle.loads(payload)
            if decoded.digest != asset.digest or decoded.dumps() != payload:
                raise ProjectStoreError("asset identity differs from its canonical payload")
        except (GeometryRefusal, TypeError, ValueError) as exc:
            raise ProjectStoreError(f"candidate geometry asset is invalid: {exc}") from exc
        prior = provided.get(decoded.digest)
        if prior is not None and prior[0] != payload:
            raise ProjectStoreError("conflicting geometry asset payloads share an identity")
        provided[decoded.digest] = (payload, decoded)
    return provided


#: How many bytes of payload the guarantee holds IN THE MEMORY OF ONE handle.
#: The limit is stated as a number because "an unbounded cache" is a leak
#: under another name. Past it, the guarantee simply stops remembering new
#: things: slower, but NEVER weaker (every miss is a full check).
_VERIFIED_PAYLOAD_BYTES = 256 * 1024 * 1024
#: 🔴 A SECOND BUDGET — FOR ENTRIES THAT COST BYTES BUT SAVE SECONDS
#: (08.09.2026, measurement S at N=2000 and a budget breakdown).
#: There used to be ONE budget, and it was eaten up by body payloads: out of
#: 77.13 MiB spent walking the history of 2000 bodies, **69.09 MiB (99.4%)
#: were the payloads of 2005 assets**, 36 KB apiece, and each such byte saves
#: 3.4 ms of parsing. Standing next to them were entries of a DIFFERENT
#: kind: the ownership-check key (`bindings`) weighs 64·N ≈ 640 KB at 10,000
#: bodies and saves ~10 s of `validate_geometry_bindings`, the reference key
#: (`refs`) weighs the same and saves a full walk of the revision. At
#: N=10,000 the sum of the payloads (~362 MB) exceeds 256 MiB on the very
#: FIRST revision, and after that `_remember_verified` remembers NOTHING —
#: including those very cheap keys. Hence the number: `history()` at
#: N=2000 is 0.32 s, at N=10,000 is 79.9 s. Contribution measurement (2000
#: bodies, 8 revisions, the same walk, its OWN process for each limit — the
#: first edition measured six limits in one process and produced a
#: non-monotonic series): a warm `history()` at a 256 MiB limit is
#: **0.32 s**, at 64 MiB — **8.64 s**, at 32 MiB — **12.59 s**, at
#: 16 MiB — **14.60 s**, at 0 — **17.79 s**. With split budgets, the same
#: series is FLAT: 0.34 · 0.35 · 0.61 · 0.57 · 0.72 s — the integrity walk
#: needs no parsed body at all. That is why there are two budgets: a large
#: one for the retained BYTES, a small one for the structure.
_VERIFIED_STRUCTURE_BYTES = 64 * 1024 * 1024
#: Counter keys. By form, they cannot collide with a 64-character hex digest
#: or with the guarantee's tuple keys.
_VERIFIED_BYTES_KEY = "verified_payload_bytes"
_VERIFIED_STRUCTURE_KEY = "verified_structure_bytes"
#: A fingerprint of the checked bytes: 32 bytes instead of a retained 36 KB
#: payload. It answers ONE question — "are these the same bytes that were
#: already parsed and found fit" — and hands the reader nothing: the parsed
#: bundle lives in the payload entry, under its own budget.
_ASSET_OK = ("asset_ok",)
#: The integrity walk's answer: "the row was read, the bytes are the same,
#: there is nothing to parse." It is not a bundle and cannot pretend to be
#: one — a reader who needs the BODY does not ask for `verify_only` and gets
#: a parsed pair, as before.
_VERIFIED_ONLY = ("verified_only",)


def _fingerprint(payload) -> bytes:
    """A fingerprint of an asset row's BYTES. The same question a byte-for-byte check asks."""
    return hashlib.sha256(payload if isinstance(payload, bytes) else payload.encode("utf-8")).digest()


def _remember_verified(verified: dict, key, value, size: int, *, structure: bool = False) -> None:
    counter = _VERIFIED_STRUCTURE_KEY if structure else _VERIFIED_BYTES_KEY
    limit = _VERIFIED_STRUCTURE_BYTES if structure else _VERIFIED_PAYLOAD_BYTES
    spent = verified.get(counter, 0)
    if spent + size > limit:
        return
    verified[key] = value
    verified[counter] = spent + size


def _read_asset(connection, project_id: str, digest: str, cache: dict | None = None,
                *, verified: dict | None = None, verify_only: bool = False):
    """Read and CHECK one asset.

    🔴 TWO CACHES, AND THEY ARE ABOUT DIFFERENT THINGS. `cache` is the memory
    of ONE transaction (`_read_history`, `audit_tasks`): while the
    transaction is open, the database underneath it does not change, and a
    second SELECT would say nothing new. `verified` is the memory of ONE
    handle BETWEEN transactions, and there is no such premise there: between
    two `get_asset` calls the file can be swapped out. So `verified` NEVER
    skips reading the row: it saves only PARSING and CHECKING, and only when
    the bytes just read MATCH the ones already checked. A swapped asset gives
    different bytes, a miss, and a full check — that is, the same
    `StoreCorrupt` as before.

    The cost this removes (measurement 07.09.2026, 205 bodies in a revision):
    every `_transaction` calls `_read_state`, which calls
    `_check_revision_assets` over ALL of the head's assets. The formula was
    `(N+2)·M + N` = 207·205 + 205 = **42,640** calls to `_read_asset` for 205
    `get_asset` calls, of which 400 s out of 502 went into
    `GeometryBundle.loads`/`_validate`.
    """
    if cache is not None and digest in cache:
        remembered = cache[digest]
        # The "row confirmed" marker is not a bundle, and it is not handed to
        # a reader who needs the BODY: they fall through to the full parse
        # below and place the already-parsed pair into the cache. Otherwise
        # `audit_tasks`, which goes through the same cache looking for real
        # bundles, would get a "no asset" refusal on a confirmed row.
        if remembered is not _VERIFIED_ONLY or verify_only:
            return remembered
    row = connection.execute("SELECT payload FROM geometry_assets WHERE digest=?", (digest,)).fetchone()
    if row is None:
        return None
    if verified is not None:
        seen = verified.get(digest)
        # What is checked is the BYTES, not the name: an asset's name is its
        # digest, and a matching name without matching bytes is precisely the
        # corruption the check below catches.
        if seen is not None and seen[0] == row[0]:
            if cache is not None:
                cache[digest] = seen
            return seen
        if verify_only:
            # 🔴 THE INTEGRITY WALK ASKS "ARE THESE THE SAME BYTES," NOT
            # "GIVE ME THE BODY" (08.09.2026). `history()` and `_read_state`
            # read EVERY asset of the head, but they never once need the
            # parsed bundle: they already remember the ownership check under
            # the `bindings` key. The fingerprint answers the same question
            # as the retained payload, but costs 32 bytes instead of 36 KB —
            # and so fits into the budget IN FULL where the payloads do not
            # (N=10,000: ~1.3 MB versus ~362 MB).
            # The row is still READ from SQLite on every walk; swapped bytes
            # give a different fingerprint, a miss, a full parse — and the
            # same `StoreCorrupt` as before. There is exactly one new premise
            # here, and it is already load-bearing for the whole store: an
            # asset's name is the sha256 of its content.
            fingerprint = verified.get((_ASSET_OK, digest))
            if fingerprint is not None and fingerprint == _fingerprint(row[0]):
                if cache is not None and digest not in cache:
                    # Completeness of the asset set is checked against the
                    # KEYS of this cache (`stored_ids != set(assets)`), so a
                    # confirmed row must be present in it — otherwise the
                    # walk would declare its own optimization to be
                    # corruption.
                    cache[digest] = _VERIFIED_ONLY
                return _VERIFIED_ONLY
    from kir.occt_geometry import GeometryBundle, GeometryRefusal

    try:
        asset = GeometryBundle.loads(row[0])
        if (asset.digest != digest or asset.dumps() != row[0]
                or asset.to_dict()["manifest"]["binding"]["project_id"] != project_id):
            raise StoreCorrupt("stored geometry asset identity/project differs from its row")
    except (GeometryRefusal, TypeError, ValueError) as exc:
        raise StoreCorrupt(f"stored geometry asset is invalid: {exc}") from exc
    value = (row[0], asset)
    if cache is not None:
        cache[digest] = value
    if verified is not None:
        _remember_verified(verified, (_ASSET_OK, digest), _fingerprint(row[0]), 128,
                           structure=True)
        _remember_verified(verified, digest, value, len(row[0]))
    return value


def _referenced_digests(revision: ProjectRevision, verified: dict | None = None) -> frozenset:
    """Digests of the bodies a revision references. Computed ONCE per handle.

    🔴 WITHOUT THIS MEMORY THE HOT PATH WOULD STAY QUADRATIC.
    `geometry_references()` goes through `addressed_outputs()`, which computes
    `output_id` (sha256) for EVERY output: at 705 bodies the profile showed
    511,834 calls to `_hash` and 30.8 s — that is, walking the revision by
    itself costs `(N+2)·M` even without reading a single asset. The set is
    derived from the revision's payload, whose identity is already checked
    byte-for-byte (`_decode_row`), so for the same `revision_id` and the same
    bytes it is the same set.
    """
    key = ("refs", revision.revision_id)
    if verified is not None:
        seen = verified.get(key)
        if seen is not None:
            return seen
    digests = frozenset(output.geometry.bundle_sha256
                        for _instance, output, _oid in revision.geometry_references())
    if verified is not None:
        # The size is stated honestly (64 characters per digest), not written
        # off to zero: "an unaccounted cache" and "an unbounded cache" are
        # the same leak.
        _remember_verified(verified, key, digests, 64 * len(digests), structure=True)
    return digests


def _check_revision_schema(revision: ProjectRevision, schema: str, *, stored: bool,
                           verified: dict | None = None) -> None:
    """A schema gate for bodies WITHOUT reading assets — the "schema" of the hot path.

    🔴 WHY THIS IS A SEPARATE FUNCTION (07.09.2026). The module header states
    the rule verbatim: «Hot paths validate schema, ownership, head and the
    addressed payload, not every old snapshot». The code did not follow the
    rule: `_read_state` walked ALL of the head's assets on EVERY transaction,
    and the cost grew as `(N+2)·M` — at 705 bodies exactly 499,140 reads
    (checked against the profile down to the unit), 74% of analysis time;
    the model `T = 7.984e-5·N² + 3.124e-2·N` (fitted on 205 and 2005 bodies,
    predicted 705 with a 2.3% error) gave ~2.3 hours at 10,000 bodies. What
    remains here is exactly what costs O(1) in the number of assets and
    still must be on the hot path: the revision has bodies, and the store
    does not know how to hold them — that is a refusal, not a slow guess.
    """
    if not _referenced_digests(revision, verified):
        return
    if schema not in _ASSET_SCHEMAS:
        error = StoreCorrupt if stored else StoreUpgradeRequired
        raise error("body-owned project outputs require explicit kir-project-store/2 upgrade")


def _check_revision_assets(connection, revision: ProjectRevision, schema: str,
                           provided: dict | None = None, *, stored: bool = False,
                           cache: dict | None = None,
                           verified: dict | None = None) -> dict:
    """Inert referential integrity; no native parser, tessellation or recipe run.

    Return only missing-on-disk assets required by this exact proposed revision.
    Existing rows are verified, never repaired by a supplied replacement.
    """
    provided = {} if provided is None else provided
    # 🔴 ONE REFERENCE MEMORY FOR BOTH PATHS. `_referenced_digests` was set up
    # for the hot read path; WRITING (`sweep_assets=True`) kept calling
    # `geometry_references()` directly and walking the WHOLE revision again —
    # and a recipe step has two such transactions. The set is the same one
    # (it was derived from `geometry_references()` in the first place), the
    # key is the `revision_id` of a payload already checked BYTE-FOR-BYTE, so
    # the check has not weakened: different bytes mean a different
    # revision_id, a miss, and a full walk.
    required = set(_referenced_digests(revision, verified))
    if provided.keys() - required:
        raise ProjectStoreError("provided geometry assets must be referenced by the proposed revision")
    if not required:
        return {}
    if schema not in _ASSET_SCHEMAS:
        error = StoreCorrupt if stored else StoreUpgradeRequired
        raise error("body-owned project outputs require explicit kir-project-store/2 upgrade")
    # 🔴 THE OWNERSHIP CHECK IS ALREADY REMEMBERED -> A PARSED BODY IS NEEDED
    # BY NO ONE HERE (08.09.2026). `bundles` is assembled FOR THE SAKE OF
    # `validate_geometry_bindings` and for nothing else; once the check's key
    # is already set, the walk only has to confirm that every row is present
    # and the bytes are the same. The rows are read, all of them, always —
    # only the cost of confirmation changes: a fingerprint instead of a
    # parse. The checking rule has not shifted: a fingerprint miss means a
    # full parse and `StoreCorrupt`, and with brought-in bytes (`provided`)
    # the check runs as before, byte-for-byte.
    binding_key = ("bindings", revision.revision_id, tuple(sorted(required)))
    settled = verified is not None and binding_key in verified
    bundles, additions = {}, {}
    for digest in sorted(required):
        supplied = provided.get(digest)
        existing = (_read_asset(connection, revision.project_id, digest, cache,
                                verified=verified,
                                verify_only=settled and supplied is None)
                    if connection is not None else None)
        if existing is _VERIFIED_ONLY:
            continue
        if existing is not None:
            if supplied is not None and supplied[0] != existing[0]:
                raise StoreCorrupt("geometry asset identity collision with different payload")
            bundles[digest] = existing[1]
        elif supplied is not None:
            additions[digest] = supplied[0]
            bundles[digest] = supplied[1]
        else:
            error = StoreCorrupt if stored else StoreAssetMissing
            raise error(f"referenced geometry asset is missing: {digest}")
    from kir.geometry_materialization import validate_geometry_bindings
    from kir.occt_geometry import GeometryRefusal

    # 🔴 THE OWNERSHIP CHECK IS A PURE FUNCTION OF TWO ALREADY-CHECKED THINGS,
    # AND SO IS PAID FOR ONCE. On the left is the revision's payload (its
    # identity already checked byte-for-byte by `_decode_row`); on the right
    # are the asset bytes (checked above by digest and, on hitting the
    # guarantee, by the BYTES THEMSELVES). So for the same `revision_id` and
    # the same set of digests the result must be the same. The key carries
    # both halves; one swapped byte is enough for `_read_asset` to miss the
    # guarantee before it is even this check's turn.
    # 🔴 WHY THE CONDITION NO LONGER REQUIRES `stored and not provided`
    # (07.09.2026, measurement of the fix at 2000 bodies). Both halves of the
    # check are byte-based WITHIN THIS SAME CALL: on the left is the
    # revision's payload (its identity checked by `_decode_row` or
    # `_payload`), on the right are bundles that are either read from the row
    # and checked BYTE-FOR-BYTE against the guarantee (`_read_asset`), or
    # brought in by the caller and parsed from their own bytes with a digest
    # check (`_provided_assets`), and will land in the database with those
    # same bytes within this same transaction. So "this revision_id is
    # correctly bound to this set of digests" is a fact about BYTES, not
    # about where they came from. The old condition left the WRITE path
    # without any memory: every edit paid for `validate_geometry_bindings`
    # twice — on commit and on the next full walk (1.9 s × 2 at 2000
    # bodies).
    reuse = verified is not None
    if reuse and binding_key in verified:
        return additions
    try:
        validate_geometry_bindings(revision, bundles)
    except (GeometryRefusal, ProjectError) as exc:
        error = StoreCorrupt if stored else ProjectStoreError
        raise error(f"geometry asset does not match its authored owner: {exc}") from exc
    if reuse:
        # 🔴 SIZE IS COUNTED BY THE KEY, NOT BY THE VALUE (review6, N-2). The
        # value here is `True`, and writing the entry off as zero was
        # tempting; but the KEY carries a tuple of ALL the revision's
        # digests and grows with the number of bodies (at 10,000 bodies that
        # is ~640 KB per entry). Zero would mean such entries are placed
        # ALWAYS, even once the limit is spent: `spent + 0 > limit` is false
        # for any `spent`. "An unaccounted cache" is the same leak as "an
        # unbounded cache," and this was my own unfinished move: I had
        # removed the zero from the neighboring `_referenced_digests` an
        # hour earlier and missed it here — I made the fix but did not close
        # the class of bug.
        _remember_verified(verified, binding_key, True, 64 * len(required), structure=True)
    return additions


def _insert_assets(connection, additions: dict) -> None:
    for digest, payload in additions.items():
        connection.execute("INSERT INTO geometry_assets VALUES (?, ?)", (digest, payload))


def _schema_downgrade(parent: ProjectRevision, child: ProjectRevision) -> bool:
    return parent.schema == PROJECT_SCHEMA_V2 and child.schema == PROJECT_SCHEMA


def _decode_row(row: tuple, project_id: str, verified: dict | None = None) -> ProjectRevision:
    """A revision row -> a checked snapshot. Parsing is paid for once per BYTES.

    🔴 A SECOND LAYER OF THE SAME BILL, MEASURED AFTER THE FIRST (07.09.2026).
    Having removed the repeated asset check, the profile named the next one:
    this function is **38.2 s out of 57.8 s** at 205 bodies, 207 calls. Every
    transaction re-parsed ONE AND THE SAME head payload and re-canonicalized
    it (`dumps()`) just to compare it with itself. The bill is the same as
    for assets: N calls × M head outputs, only with a smaller constant.

    The guarantee saves PARSING here too, not READING: the row always comes
    from SQLite, and the remembered snapshot is handed out ONLY when the
    WHOLE ROW matches — number, identity, project, parent, and the payload
    bytes. Swapping any field gives a miss and a full check, that is, the
    same `StoreCorrupt`. `ProjectRevision` is immutable
    (`frozen=True, slots=True`), so a shared instance never lets anyone edit
    someone else's snapshot.
    """
    sequence, revision_id, row_project, parent, payload = row
    if type(sequence) is not int or sequence < 0 or row_project != project_id:
        raise StoreCorrupt("stored revision has a foreign project or invalid sequence")
    key = ("revision", revision_id)
    if verified is not None:
        seen = verified.get(key)
        if seen is not None and seen[0] == row:
            return seen[1]
    try:
        revision = ProjectRevision.loads(payload)
    except ProjectError as exc:
        raise StoreCorrupt(f"stored revision payload is invalid: {exc}") from exc
    if (revision.revision_id != revision_id or revision.project_id != project_id
            or revision.parent_revision != parent or revision.dumps() != payload):
        raise StoreCorrupt("stored payload identity/canonical encoding differs from its row")
    if verified is not None:
        _remember_verified(verified, key, (row, revision), len(payload), structure=True)
    return revision


def _check_parent(connection: sqlite3.Connection, row: tuple) -> None:
    sequence, _, project_id, parent, _ = row
    if sequence == 0:
        if parent is not None:
            raise StoreCorrupt("root snapshot cannot have a parent")
    elif connection.execute(
            "SELECT sequence, project_id FROM revisions WHERE revision_id=?",
            (parent,)).fetchone() != (sequence - 1, project_id):
        raise StoreCorrupt("stored revision has a missing or inconsistent immediate parent")


def _read_state(connection: sqlite3.Connection, *, verified: dict | None = None,
                sweep_assets: bool = True) -> _State:
    """Schema, identity, head. `sweep_assets` — whether to walk ALL of the head's assets.

    🔴 `sweep_assets=False` IS THE HEADER'S RULE, NOT A RELAXATION. The hot
    read path (`head`, `get`, `get_asset`) checks the schema, ownership, the
    head's payload BYTE-FOR-BYTE, and — in `get_asset` — the ADDRESSED asset
    in full (bytes plus parsing). The remaining `M-1` head assets are not
    read on this path, exactly as stated in the module header. A full walk
    is still reachable through the existing name `history()`
    (`_read_history` -> `_check_revision_assets` over EVERY revision) — no
    new public names are introduced.

    What this STOPPED catching on the hot path, and is named here: the loss
    or corruption of an asset that this call did NOT touch. It is caught by
    `history()` and by any WRITE (`sweep_assets=True` on a write transaction
    and on creation): writing over a head whose bodies have drifted apart is
    still not allowed.
    """
    version = connection.execute("PRAGMA user_version").fetchone()
    schema = next((name for name, number in _SCHEMAS.items() if version == (number,)), None)
    if (connection.execute("PRAGMA application_id").fetchone() != (_APPLICATION_ID,)
            or schema is None):
        raise StoreCorrupt("foreign or unsupported project store schema/version")
    objects = connection.execute(
        "SELECT name, type, sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'").fetchall()
    expected = {"revisions": _REVISIONS_SQL, "project_store": _STORE_SQL}
    if schema in _ASSET_SCHEMAS:
        expected["geometry_assets"] = _ASSETS_SQL
    indexes = {}
    if schema in _REALIZATION_SCHEMAS:
        from kir.project_realization_store import realization_tables, RESOLUTION_INDEXES
        expected.update(realization_tables(schema))
        if schema in _RESOLUTION_SCHEMAS:
            indexes = RESOLUTION_INDEXES
            expected.update(indexes)
    if schema in _TASK_SCHEMAS:
        from kir.project_tasks import TASK_TABLES
        expected.update(TASK_TABLES)
    if schema in _CREATE_SCHEMAS:
        from kir.project_create_store import create_tables
        expected.update(create_tables(schema))
    if (len(objects) != len(expected) or any(
            name not in expected or kind != ("index" if name in indexes else "table") or not isinstance(sql, str)
            or _normalized_sql(sql) != _normalized_sql(expected[name])
            for name, kind, sql in objects)):
        raise StoreCorrupt("project store has foreign/changed tables, indexes, views or triggers")
    if connection.execute("PRAGMA journal_mode").fetchone() != ("delete",):
        raise StoreCorrupt("unsupported project store journal mode; expected DELETE")
    rows = connection.execute(
        "SELECT singleton, schema_version, store_id, project_id, head_revision "
        "FROM project_store").fetchall()
    if len(rows) != 1 or rows[0][0] != 1 or rows[0][1] != schema:
        raise StoreCorrupt("project store must have exactly one recognized owner/head")
    _, _, store_id, project_id, head_revision = rows[0]
    if not isinstance(store_id, str) or not _HEX32.fullmatch(store_id):
        raise StoreCorrupt("project store identity is malformed")
    row = connection.execute(f"SELECT {_ROW} FROM revisions WHERE revision_id=?",
                             (head_revision,)).fetchone()
    if row is None:
        raise StoreCorrupt("project head points to a missing snapshot")
    head = _decode_row(row, project_id, verified)
    if sweep_assets:
        _check_revision_assets(connection, head, schema, stored=True, verified=verified)
    else:
        _check_revision_schema(head, schema, stored=True, verified=verified)
    if head.revision_id != head_revision:
        raise StoreCorrupt("head lookup returned a different revision identity")
    _check_parent(connection, row)
    latest = connection.execute(
        "SELECT sequence, revision_id FROM revisions ORDER BY sequence DESC LIMIT 1").fetchone()
    if latest != (row[0], head_revision):
        raise StoreCorrupt("head is not the last committed history entry")
    return _State(project_id, store_id, head, row[0], schema, verified)


def _find_revision(connection: sqlite3.Connection, state: _State,
                   revision_id: str) -> ProjectRevision | None:
    row = connection.execute(f"SELECT {_ROW} FROM revisions WHERE revision_id=?",
                             (revision_id,)).fetchone()
    if row is None:
        return None
    # 🔴 FIVE FULL-MODEL PARSES WERE PAID FOR ON A SINGLE RECIPE STEP HERE
    # (07.09.2026). `read_task` (x2), `store.get`, and two journal writes call
    # `_find_revision` for ONE AND THE SAME base revision; without the
    # guarantee, each one redid `ProjectRevision.loads` and `dumps()` over
    # the whole payload. At 2000 instances that is 1.51 s per element versus
    # 0.25 s at 250 — "reread the whole model for every element," literally.
    revision = _decode_row(row, state.project_id, state.verified)
    # `get(revision_id)` is the hot read path: the schema and payload of the
    # addressed revision, but not a walk of ALL its assets (the header's
    # rule).
    _check_revision_schema(revision, state.schema, stored=True, verified=state.verified)
    if revision.revision_id != revision_id:
        raise StoreCorrupt("revision lookup returned a different requested identity")
    if row[0] > state.head_sequence:
        raise StoreCorrupt("requested snapshot is beyond the committed head")
    _check_parent(connection, row)
    return revision


def _rollback(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error as exc:
            raise StoreCommitUnknown(
                "rollback acknowledgement failed; inspect history before retrying "
                "the same revision") from exc


def _commit(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("COMMIT")
    except sqlite3.Error as exc:
        if connection.in_transaction:
            _rollback(connection)
            raise _sqlite_error(exc) from exc
        raise StoreCommitUnknown(
            "commit acknowledgement failed; inspect history or retry the exact "
            "same revision without changing its parent") from exc


def _sync_parent(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _payload(revision: ProjectRevision) -> tuple[str, ProjectRevision]:
    """Do not persist an object whose bytes this same reader would refuse.

    Normal frozen revisions are already consistent. Revalidation also guards
    subclass/custom-construction mistakes at the actual durability boundary.
    """
    try:
        payload = revision.dumps()
        decoded = ProjectRevision.loads(payload)
    except (ProjectError, TypeError, ValueError) as exc:
        raise ProjectStoreError(f"candidate revision payload is invalid: {exc}") from exc
    if (decoded.revision_id != revision.revision_id
            or decoded.project_id != revision.project_id
            or decoded.parent_revision != revision.parent_revision
            or decoded.dumps() != payload):
        raise ProjectStoreError("candidate revision identity differs from its canonical payload")
    # All subsequent persistence decisions use this canonical base-class
    # snapshot, not caller-overridden methods such as geometry_references().
    return payload, decoded


def _read_history(connection: sqlite3.Connection, state: _State) -> tuple[ProjectRevision, ...]:
    """Audit within the caller's read/write transaction; never open or commit it.

    🔴 THE COST `state.verified` REMOVES HERE (measurement 07.09.2026, 2000
    bodies). `accept_proposal` calls `history()` on EVERY edit, and the walk
    re-read and re-parsed ALL revisions from scratch: `(R-1)` head parses at
    0.46 s each, `(R-1)` ownership checks at 1.9 s each, and 2005 bundle
    parses at 3.4 ms each — that is, 24.7 s at 8 revisions and +2.5 s for
    every subsequent edit. The full walk stays full: EVERY row is read from
    SQLite and checked BYTE-FOR-BYTE; the guarantee skips only the repeated
    PARSE of bytes that matched, so a swapped asset or payload still
    produces `StoreCorrupt`.
    """
    if not connection.in_transaction:
        raise ProjectStoreError("history audit requires an existing transaction")
    if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise StoreCorrupt("SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise StoreCorrupt("project store contains broken revision references")
    revisions, previous, previous_project, assets = [], None, None, {}
    for index, row in enumerate(connection.execute(f"SELECT {_ROW} FROM revisions ORDER BY sequence")):
        revision = _decode_row(row, state.project_id, state.verified)
        _check_revision_assets(connection, revision, state.schema, stored=True, cache=assets,
                               verified=state.verified)
        if row[0] != index or revision.parent_revision != previous:
            raise StoreCorrupt("project history has a gap, branch or missing parent")
        if previous_project is not None and _schema_downgrade(previous_project, revision):
            raise StoreCorrupt("project history contains an unsupported authored-schema downgrade")
        revisions.append(revision)
        previous = revision.revision_id
        previous_project = revision
    if previous != state.head.revision_id or len(revisions) != state.head_sequence + 1:
        raise StoreCorrupt("head does not match the complete stored history")
    if state.schema in _TASK_SCHEMAS:
        from kir.project_tasks import audit_tasks
        # Retained branch candidates own their assets even before head accepts
        # them. The task audit extends the SAME verified asset cache.
        audit_tasks(connection, state, asset_cache=assets)
    if state.schema in _ASSET_SCHEMAS:
        stored_ids = {row[0] for row in connection.execute("SELECT digest FROM geometry_assets")}
        if stored_ids != set(assets):
            raise StoreCorrupt("geometry assets contain entries outside the authored history")
    if state.schema in _REALIZATION_SCHEMAS:
        from kir.project_realization_store import audit_streams
        audit_streams(connection, state)
    if state.schema in _CREATE_SCHEMAS:
        from kir.project_create_store import audit_publications
        audit_publications(connection, state)
    return tuple(revisions)


def _prepare_revision_commit(revision, expected_revision, assets):
    if not isinstance(revision, ProjectRevision):
        raise ProjectStoreError("commit requires a ProjectRevision")
    if expected_revision != revision.parent_revision:
        raise StoreConflict("expected_revision must equal the proposed snapshot's parent")
    payload, revision = _payload(revision)
    return payload, revision, _provided_assets(assets)


def _commit_prepared_revision(connection, state, prepared, expected_revision) -> CommitResult:
    """The single SQL append/redelivery implementation; transaction is caller-owned."""
    if not connection.in_transaction:
        raise ProjectStoreError("revision append requires an existing transaction")
    payload, revision, provided = prepared
    if revision.project_id != state.project_id:
        raise StoreConflict("cannot commit a revision from another project")
    stored = _find_revision(connection, state, revision.revision_id)
    if stored is not None:
        if stored.dumps() != payload:
            raise StoreCorrupt("revision identity collision with different payload")
        additions = _check_revision_assets(connection, stored, state.schema, provided, stored=True,
                                           verified=state.verified)
        if additions:
            raise StoreCorrupt("stored revision lost its geometry assets; exact retry is not repair")
        return CommitResult(revision.revision_id, state.head.revision_id, False)
    if revision.parent_revision is None:
        raise StoreConflict("new root cannot replace an existing project history")
    if expected_revision != state.head.revision_id:
        raise StoreConflict(
            f"stale or missing parent {expected_revision}; current head is "
            f"{state.head.revision_id}; rebase before committing")
    if _schema_downgrade(state.head, revision):
        raise StoreConflict("authored schema cannot downgrade from /2 to /1 within project history")
    if state.head_sequence == (1 << 63) - 1:
        raise ProjectStoreError("SQLite history sequence is exhausted")
    additions = _check_revision_assets(connection, revision, state.schema, provided,
                                       verified=state.verified)
    _insert_assets(connection, additions)
    connection.execute("INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
                       (state.head_sequence + 1, revision.revision_id,
                        revision.project_id, revision.parent_revision, payload))
    result = connection.execute(
        "UPDATE project_store SET head_revision=? WHERE singleton=1 AND head_revision=?",
        (revision.revision_id, expected_revision))
    if result.rowcount != 1:
        raise StoreConflict("head compare-and-swap failed")
    return CommitResult(revision.revision_id, revision.revision_id, True)


def _commit_revision(connection: sqlite3.Connection, state: _State, revision: ProjectRevision, *,
                     expected_revision: str | None, assets: tuple | list = ()) -> CommitResult:
    """Validate and append without BEGIN/COMMIT or opening another connection.

    A caller doing another append in the same transaction must refresh _State
    with _read_state first. The helper does not own rollback on caller failure.
    """
    prepared = _prepare_revision_commit(revision, expected_revision, assets)
    return _commit_prepared_revision(connection, state, prepared, expected_revision)


@dataclass(frozen=True, slots=True)
class ProjectStore:
    """Use create/open; methods hold no shared connection across calls/processes.

    One database contains one linear, append-only project history. Opening a
    handle pins its store identity; replacing the file cannot silently redirect
    that handle to another store, even one with the same logical project_id.
    """

    path: Path
    project_id: str
    store_id: str
    readonly: bool = True
    timeout: float = 5.0
    #: The guarantee of THIS handle: `{digest: (bytes, bundle)}` plus marks
    #: of a checked ownership. Not global (another handle does not inherit
    #: its check), not on disk (the storage format is untouched), takes no
    #: part in comparing or hashing the handle. It lives exactly as long as
    #: the handle does.
    _verified: dict = field(default_factory=dict, compare=False,
                            hash=False, repr=False)

    @classmethod
    def create(cls, path: str | os.PathLike[str], initial: ProjectRevision, *,
               timeout: float = 5.0, schema: str = STORE_SCHEMA,
               assets: tuple | list = ()) -> ProjectStore:
        """Exclusively create and commit a root snapshot, never adopt a file.

        A failed initialization leaves its newly created file for inspection.
        No existing file, including an empty/foreign one, is removed or repaired.
        The parent directory must already exist. The returned handle is writable.
        Body-owned roots require explicit schema /2 and all referenced assets.
        """
        path, timeout = _path(path), _timeout(timeout)
        if not isinstance(schema, str) or schema not in _SCHEMAS:
            raise ProjectStoreError("unsupported project store creation schema")
        if not isinstance(initial, ProjectRevision):
            raise ProjectStoreError("initial must be a ProjectRevision")
        if initial.parent_revision is not None:
            raise StoreConflict("initial revision has a parent; import its complete history first")
        payload, initial = _payload(initial)
        provided = _provided_assets(assets)
        additions = _check_revision_assets(None, initial, schema, provided)
        connection = None
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                raise StoreExists(
                    f"refusing creation beside an existing SQLite recovery artifact: {sidecar}")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise StoreExists(f"refusing to overwrite existing project-store path: {path}") from exc
        except OSError as exc:
            raise ProjectStoreError(f"cannot create project store: {exc}") from exc
        os.close(descriptor)
        try:
            connection = _connect(path, readonly=False, timeout=timeout, initializing=True)
            connection.execute("BEGIN IMMEDIATE")
            if (connection.execute("SELECT name FROM sqlite_schema").fetchall()
                    or connection.execute("PRAGMA application_id").fetchone() != (0,)
                    or connection.execute("PRAGMA user_version").fetchone() != (0,)):
                raise StoreCorrupt("newly created path was initialized by another writer")
            connection.execute(_REVISIONS_SQL)
            connection.execute(_STORE_SQL)
            if schema in _ASSET_SCHEMAS:
                connection.execute(_ASSETS_SQL)
            if schema in _REALIZATION_SCHEMAS:
                from kir.project_realization_store import realization_tables, RESOLUTION_INDEXES
                for sql in realization_tables(schema).values():
                    connection.execute(sql)
                if schema in _RESOLUTION_SCHEMAS:
                    for sql in RESOLUTION_INDEXES.values():
                        connection.execute(sql)
            if schema in _TASK_SCHEMAS:
                from kir.project_tasks import TASK_TABLES
                for sql in TASK_TABLES.values():
                    connection.execute(sql)
            if schema in _CREATE_SCHEMAS:
                from kir.project_create_store import create_tables
                for sql in create_tables(schema).values():
                    connection.execute(sql)
            connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={_SCHEMAS[schema]}")
            _insert_assets(connection, additions)
            connection.execute(
                "INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
                (0, initial.revision_id, initial.project_id, None, payload))
            connection.execute("INSERT INTO project_store VALUES (1, ?, ?, ?, ?)",
                               (schema, uuid.uuid4().hex, initial.project_id,
                                initial.revision_id))
            _read_state(connection)
            _commit(connection)
            _sync_parent(path)
        except sqlite3.Error as exc:
            if connection is not None:
                _rollback(connection)
            raise _sqlite_error(exc) from exc
        except OSError as exc:
            if connection is not None:
                _rollback(connection)
            raise ProjectStoreError(
                f"initialization durability failed; file retained for inspection: {exc}") from exc
        except BaseException:
            if connection is not None:
                _rollback(connection)
            raise
        finally:
            if connection is not None:
                connection.close()
        return cls.open(path, readonly=False, timeout=timeout)

    @classmethod
    def open(cls, path: str | os.PathLike[str], *, readonly: bool = True,
             timeout: float = 5.0) -> ProjectStore:
        """Open an existing recognized database; no implicit create/migration."""
        if type(readonly) is not bool:
            raise ProjectStoreError("readonly must be bool")
        path, timeout = _path(path), _timeout(timeout)
        connection = _connect(path, readonly=readonly, timeout=timeout)
        try:
            connection.execute("BEGIN")
            # Opening is a READ, and lives by the same header rule: schema,
            # store identity, head payload. Walking all M assets here would
            # mean paying for them TWICE — once on opening and again when
            # they are actually read.
            state = _read_state(connection, sweep_assets=False)
            return cls(path, state.project_id, state.store_id, readonly, timeout)
        except sqlite3.Error as exc:
            raise _sqlite_error(exc) from exc
        finally:
            connection.close()

    @contextmanager
    def _transaction(self, *, write: bool = False, migration: bool = False) -> Iterator[tuple[sqlite3.Connection, _State]]:
        if write and self.readonly:
            raise StoreReadOnly("commit requires explicit open(readonly=False)")
        connection = _connect(self.path, readonly=self.readonly, timeout=self.timeout)
        try:
            if migration:
                if not write:
                    raise ProjectStoreError("migration requires a write transaction")
                # SQLite requires this BEFORE BEGIN for the documented
                # create/copy/drop/rename table-rebuild procedure.
                connection.execute("PRAGMA foreign_keys=OFF")
                if connection.execute("PRAGMA foreign_keys").fetchone() != (0,):
                    raise ProjectStoreError("cannot disable foreign keys for explicit migration")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            # WRITING pays for the full walk, READING does not. You cannot
            # write over a head whose bodies have drifted apart; you can
            # read an addressed body, and that is exactly what the module
            # header promises.
            state = _read_state(connection, verified=self._verified, sweep_assets=write)
            if state.store_id != self.store_id or state.project_id != self.project_id:
                raise StoreCorrupt("database identity changed since this store handle was opened")
            yield connection, state
            if write:
                if migration and connection.execute("PRAGMA foreign_key_check").fetchall():
                    raise StoreCorrupt("migration would leave broken foreign keys")
                _commit(connection)
        except sqlite3.Error as exc:
            _rollback(connection)
            raise _sqlite_error(exc) from exc
        except BaseException:
            _rollback(connection)
            raise
        finally:
            try:
                if migration and not connection.in_transaction:
                    # If rollback itself was not acknowledged, SQLite ignores
                    # FK changes inside the still-active transaction. Preserve
                    # StoreCommitUnknown and close this connection instead of
                    # masking uncertainty with a secondary restoration error.
                    connection.execute("PRAGMA foreign_keys=ON")
                    if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
                        raise ProjectStoreError("foreign key enforcement was not restored")
            finally:
                connection.close()

    def head(self) -> ProjectRevision:
        with self._transaction() as (_, state):
            return state.head

    def status(self, *, limit: int = 20, after_stream: str | None = None) -> dict:
        """One read snapshot of authoring and bounded local native-scope records.

        No compilation, geometry evaluation, discovery, model query or write.
        A pending input does not prove delivery; a checkpoint is historical
        selected-field evidence, not acceptance of the whole current BIM model.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ProjectStoreError("status limit must be an integer from 1 to 100")
        if after_stream is not None and (type(after_stream) is not str or not _HEX64.fullmatch(after_stream)):
            raise ProjectStoreError("status cursor must be a lowercase stream SHA-256")
        # Status must never recover a hot journal through a writable handle.
        # Preserve the pinned store identity, but open its one connection ro.
        reader = self if self.readonly else replace(self, readonly=True)
        with reader._transaction() as (connection, state):
            supported = state.schema in _REALIZATION_SCHEMAS
            native = {"streams": [], "has_more": False, "next_cursor": None,
                "catalog_complete": False, "returned_scopes_readable": True,
                "catalog_diagnostic": "ledger_not_supported",
                "continuation_consistency": "new_read_snapshot_each_call"}
            if supported:
                from kir.project_realization_store import status_page
                native = status_page(connection, state, limit=limit, after_stream=after_stream)
            return {"schema": "kir-project-status/1", "store_id": state.store_id,
                "project_id": state.project_id, "store_schema": state.schema,
                "snapshot_scope": "one_local_read_transaction", "read_only": True,
                "authoring": {"revision_id": state.head.revision_id, "parent_revision": state.head.parent_revision,
                    "revision_count": state.head_sequence + 1, "intent": state.head.intent[:1000],
                    "intent_truncated": len(state.head.intent) > 1000,
                    "instances": len(state.head.instances), "outputs": sum(len(item.outputs) for item in state.head.instances)},
                "native": {**native, "ledger_supported": supported, "live_model_observed": False,
                    "whole_project_acceptance": "not_established", "after_stream": after_stream, "limit": limit}}

    @property
    def schema(self) -> str:
        """The current storage schema; another handle may explicitly upgrade it."""
        with self._transaction() as (_, state):
            return state.schema

    def upgrade_schema(self, target_schema: str, *, expected_revision: str) -> bool:
        """Explicitly enable assets and/or Level streams without rewriting revisions.

        Tables, owner version and SQLite header change in one transaction.
        Returns True if upgraded, False if already at the requested schema.
        Both cases require the current head. This does not upgrade an authored
        project's schema or create a new authored revision; that is a separate
        ProjectRevision operation followed by normal expected-head commit.
        """
        if target_schema not in (GEOMETRY_STORE_SCHEMA, *_REALIZATION_SCHEMAS):
            raise ProjectStoreError("only explicit upgrades to kir-project-store/2 through /8 are supported")
        with self._transaction(write=True, migration=target_schema in _RESOLUTION_SCHEMAS) as (connection, state):
            if expected_revision != state.head.revision_id:
                raise StoreConflict("schema upgrade requires the current expected revision")
            if state.schema == target_schema:
                return False
            if _SCHEMAS[state.schema] > _SCHEMAS[target_schema]:
                raise StoreConflict("project store schema cannot downgrade")
            if state.schema == STORE_SCHEMA:
                connection.execute(_ASSETS_SQL)
            if target_schema in _REALIZATION_SCHEMAS:
                from kir.project_realization_store import realization_tables, migrate_resolution_schema, RESOLUTION_INDEXES
                if state.schema == REALIZATION_STORE_SCHEMA and target_schema in _RESOLUTION_SCHEMAS:
                    migrate_resolution_schema(connection)
                elif state.schema not in _REALIZATION_SCHEMAS:
                    for sql in realization_tables(target_schema).values():
                        connection.execute(sql)
                    if target_schema in _RESOLUTION_SCHEMAS:
                        for sql in RESOLUTION_INDEXES.values():
                            connection.execute(sql)
            if target_schema in _TASK_SCHEMAS and state.schema not in _TASK_SCHEMAS:
                from kir.project_tasks import TASK_TABLES
                for sql in TASK_TABLES.values():
                    connection.execute(sql)
            if target_schema in _CREATE_SCHEMAS and state.schema not in _CREATE_SCHEMAS:
                from kir.project_create_store import CREATE_TABLES
                for sql in CREATE_TABLES.values():
                    connection.execute(sql)
            if target_schema in _CREATE_RESOLUTION_SCHEMAS and state.schema not in _CREATE_RESOLUTION_SCHEMAS:
                from kir.project_create_store import CREATE_RESOLUTION_TABLES
                for sql in CREATE_RESOLUTION_TABLES.values():
                    connection.execute(sql)
            if target_schema == STAGED_CREATE_STORE_SCHEMA:
                from kir.project_create_store import CREATE_IMPORT_TABLES
                for sql in CREATE_IMPORT_TABLES.values():
                    connection.execute(sql)
            connection.execute("UPDATE project_store SET schema_version=? WHERE singleton=1",
                               (target_schema,))
            connection.execute(f"PRAGMA user_version={_SCHEMAS[target_schema]}")
            upgraded = _read_state(connection)
            if upgraded.head.revision_id != state.head.revision_id or upgraded.store_id != state.store_id:
                raise StoreCorrupt("schema upgrade changed store or revision identity")
            return True

    def get(self, revision_id: str) -> ProjectRevision:
        if not isinstance(revision_id, str) or not _HEX64.fullmatch(revision_id):
            raise StoreNotFound("revision_id must name an existing SHA-256 revision")
        with self._transaction() as (connection, state):
            revision = _find_revision(connection, state, revision_id)
            if revision is None:
                raise StoreNotFound(f"revision is not in this store: {revision_id}")
            return revision

    def get_asset(self, digest: str) -> GeometryBundle:
        """Load one bounded, hash-checked bundle without parsing its BRep.

        This is integrity/ownership lookup, not proof that the saved preview or
        measurements describe the body. Materialization remains explicit.
        """
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise StoreNotFound("asset digest must be a lowercase SHA-256 identity")
        with self._transaction() as (connection, state):
            if state.schema not in _ASSET_SCHEMAS:
                raise StoreUpgradeRequired("geometry assets require explicit kir-project-store/2 upgrade")
            found = _read_asset(connection, state.project_id, digest,
                                verified=self._verified)
            if found is None:
                # 🔴 "NOT IN THE STORE" AND "THE HEAD REFERENCES IT BUT THE
                # ROW IS MISSING" ARE DIFFERENT FACTS. The first is a
                # question about the wrong body; the second is CORRUPTION,
                # and it must be named the same way it was named when the
                # full walk paid for it. What is asked is exactly the
                # reference memory, that is, O(1) per handle, not reading
                # all M rows.
                if digest in _referenced_digests(state.head, self._verified):
                    raise StoreCorrupt(
                        f"referenced geometry asset is missing: {digest}")
                raise StoreNotFound(f"geometry asset is not in this store: {digest}")
            return found[1]

    def get_assets(self, digests) -> dict:
        """Read a SET of bodies in ONE transaction. The check for each is the same.

        🔴 THE NUMBER THAT PROMPTED THIS NAME (07.09.2026, N=2000). `get_asset`
        opens ITS OWN transaction, and a transaction means `_read_state`:
        seven SQL queries, a check of the schema, the head, and the parent.
        Scene analysis reads bodies one at a time, and at 2000 bodies this
        overhead cost **14.07 s**, whereas the same 2000 reads inside ONE
        transaction cost **0.22 s** (64x). What was being paid for was not
        reading the bodies, but repeating the store's check 2000 times over.

        THERE IS NO WEAKENING, AND THIS IS NOT A PROMISE, IT IS THE SAME
        CODE. Every digest passes through the same `_read_asset`: the row is
        read from SQLite, the bytes are checked, and the remembered value is
        handed out only on a match. The loss of a body the head references
        is called `StoreCorrupt`, not "no such thing" — exactly as in
        `get_asset`. What actually stopped repeating is the check of the
        STORE: it is done once per set, inside a single point of reading,
        where the database underneath us does not change.

        Returns `{digest: GeometryBundle}`; repeats in the request collapse
        into one.
        """
        ordered = tuple(digests)
        for digest in ordered:
            if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
                raise StoreNotFound("asset digest must be a lowercase SHA-256 identity")
        if not ordered:
            return {}
        found: dict = {}
        with self._transaction() as (connection, state):
            if state.schema not in _ASSET_SCHEMAS:
                raise StoreUpgradeRequired("geometry assets require explicit kir-project-store/2 upgrade")
            referenced = None
            for digest in ordered:
                if digest in found:
                    continue
                row = _read_asset(connection, state.project_id, digest,
                                  verified=self._verified)
                if row is None:
                    if referenced is None:
                        referenced = _referenced_digests(state.head, self._verified)
                    if digest in referenced:
                        raise StoreCorrupt(
                            f"referenced geometry asset is missing: {digest}")
                    raise StoreNotFound(f"geometry asset is not in this store: {digest}")
                found[digest] = row[1]
        return found

    def history(self) -> tuple[ProjectRevision, ...]:
        """Audit/return every snapshot in one read transaction, root to head.

        Unlike head/get/commit, this intentionally reads the entire history,
        verifies authored-schema transitions, and audits all retained assets.
        Every row is still READ from SQLite on every call; this handle's
        guarantee only skips re-PARSING bytes it already checked and found
        identical, so a swapped payload or asset still refuses here.
        """
        with self._transaction() as (connection, state):
            return _read_history(connection, state)

    def reserve_level_update(self, record, *, expected_checkpoint: str | None,
                             expected_project_revision: str | None = None):
        """Persist exact update input and one pending reservation, never send it.

        Authoring head is not changed. An idempotent acknowledgement is NOT
        permission to resend. Unknown execution leaves the reservation pending.
        An optional authored-head pin is checked atomically with the reservation;
        it does not lock authoring for the duration of native execution.
        """
        from kir.project_realization_store import checked_archive, reserve
        prepared = checked_archive(record)
        with self._transaction(write=True) as (connection, state):
            return reserve(connection, state, prepared, expected_checkpoint,
                           expected_project_revision=expected_project_revision)

    def reserve_create_publication(self, record, *, expected_revision: str, submission=None):
        """Retain exact Archive/2 input and output owners before any dispatch.

        A duplicate only acknowledges the existing reservation; it never grants
        replay, even when the authored head has advanced since that input.
        """
        from kir.project_create_store import checked_input, reserve, checked_submission
        value = checked_input(record)
        fresh = checked_submission(value, submission)
        with self._transaction(write=True) as (connection, state):
            return reserve(connection, state, value, expected_revision, submission=fresh)

    def record_create_receipt(self, evidence):
        """Retain an original bound receipt, without author-head or scope release."""
        from kir.project_create_store import record_receipt
        with self._transaction(write=True) as (connection, state):
            return record_receipt(connection, state, evidence)

    def release_create_not_started(self, evidence, *, expected_archive_digest: str):
        """Release exact output owners only under fresh bound native no-start.

        Archive/UUID/receipts remain retained forever. This does not grant a
        resend or assert a currently open document; no authored-head CAS occurs.
        """
        from kir.project_create_store import release_not_started
        with self._transaction(write=True) as (connection, state):
            return release_not_started(connection, state, evidence, expected_archive_digest)

    def get_create_resolution(self, archive_digest: str):
        """Read inert retained no-start resolution; never restore fresh authority."""
        from kir.project_create_store import read_resolution
        reader = self if self.readonly else replace(self, readonly=True)
        with reader._transaction() as (connection, state):
            return read_resolution(connection, state, archive_digest)

    def get_create_receipts(self, archive_digest: str):
        """Read inert retained receipts; never reconstruct fresh execution evidence."""
        from kir.project_create_store import read_receipts
        reader = self if self.readonly else replace(self, readonly=True)
        with reader._transaction() as (connection, state):
            return read_receipts(connection, state, archive_digest)

    def get_create_publication(self, archive_digest: str):
        """Read inert input/ownership through an explicitly read-only connection."""
        from kir.project_create_store import read_publication
        reader = self if self.readonly else replace(self, readonly=True)
        with reader._transaction() as (connection, state):
            return read_publication(connection, state, archive_digest)

    def find_create_publication(self, *, journal_id: str, operation_id: str):
        """Find inert reserved input by caller-known identity, never resend it."""
        from kir.project_create_store import find_publication
        reader = self if self.readonly else replace(self, readonly=True)
        with reader._transaction() as (connection, state):
            return find_publication(connection, state, journal_id=journal_id, operation_id=operation_id)

    def commit_level_settlement(self, qualified, *, expected_checkpoint: str | None,
                                expected_pending_archive: str):
        """Atomically retain qualified evidence and advance this stream only."""
        from kir.project_realization_store import checked_settlement, settle
        prepared = checked_settlement(qualified)
        with self._transaction(write=True) as (connection, state):
            return settle(connection, state, prepared, expected_checkpoint, expected_pending_archive)

    def level_baseline(self, stream_id: str):
        """Read inert original/checkpoint/pending claims, not a fresh observation."""
        from kir.project_realization_store import read_baseline
        with self._transaction() as (connection, state):
            return read_baseline(connection, state, stream_id)

    def get_level_update_archive(self, digest: str):
        """Read a checked saved record; it has lookup but no execute method."""
        from kir.project_realization_store import read_update_archive
        with self._transaction() as (connection, state):
            return read_update_archive(connection, state, digest)

    def get_level_settlement(self, digest: str) -> dict:
        """Read detached settlement claims; never reconstruct Qualified evidence."""
        from kir.project_realization_store import read_settlement
        with self._transaction() as (connection, state):
            return read_settlement(connection, state, digest)

    def commit_level_not_started(self, qualified, *, expected_checkpoint: str | None,
                                 expected_pending_archive: str):
        """Retain bound terminal not_started evidence; clear only its pending."""
        from kir.project_realization_store import checked_resolution, resolve_not_started
        prepared = checked_resolution(qualified)
        with self._transaction(write=True) as (connection, state):
            return resolve_not_started(connection, state, prepared, expected_checkpoint, expected_pending_archive)

    def get_level_resolution(self, digest: str) -> dict:
        """Read inert not_started evidence, never a fresh qualification or retry grant."""
        from kir.project_realization_store import read_resolution
        with self._transaction() as (connection, state):
            return read_resolution(connection, state, digest)

    def get_level_resolution_for_archive(self, archive_digest: str) -> dict | None:
        """Lookup after lost acknowledgement using the original archived input."""
        from kir.project_realization_store import read_resolution_for_archive
        with self._transaction() as (connection, state):
            return read_resolution_for_archive(connection, state, archive_digest)

    def commit(self, revision: ProjectRevision, *, expected_revision: str | None,
               assets: tuple | list = ()) -> CommitResult:
        """Append against current head, or acknowledge an exact prior delivery.

        Even on redelivery, expected_revision must be that snapshot's parent.
        A historical redelivery never resets head. The returned head is the
        transaction's observation, not a promise that nobody can commit later.
        Root redelivery can use expected_revision=None; a new root is forbidden.
        Assets must be referenced by this proposal. Required new assets are
        inserted in the same transaction as the revision/head; stale proposals
        cannot leave orphan assets. Existing corruption is not repaired by retry.
        """
        prepared = _prepare_revision_commit(revision, expected_revision, assets)
        with self._transaction(write=True) as (connection, state):
            return _commit_prepared_revision(connection, state, prepared, expected_revision)
