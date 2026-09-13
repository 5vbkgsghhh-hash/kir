"""Transparent gzip fallback for on-disk decompile snapshots.

A snapshot directory (``backend/data/decompile/<change_stamp>/``) holds
``L0.jsonl``, the side indexes (``curve.index.json``, ``curtain.index
.json``, ``sketch.index.json``, ``family_placement.index.json``,
``group.index.json``) and — since 2026-08-21 — the four fold-stage
artifacts (``passport.json``, ``tree.json``, ``verify.json``,
``named.json``): the big, cold-once-a-run files, 13-47MB raw per document
for L0 and up to 206MB for a single passport.
``tools/snapshot_janitor.py`` gzips these IN PLACE once a snapshot has
gone quiet (``L0.jsonl`` -> ``L0.jsonl.gz``, same name plus suffix, raw
file removed) — gzip gets ~14x on this corpus, and every reader must keep
working unchanged afterwards.

🔴 MEASURED 2026-08-21, WHY THE LIST GREW FROM SIX NAMES TO TEN. Corpus 5.0
GB, disk at 84%. `passport.json` 1001 MB (28 decompiles), `named.json` 422
MB, `tree.json` 416 MB, `verify.json` 342 MB — 2.18 GB, twice everything
the janitor used to be able to touch. They could not be compressed — not
because of a property of the data, but because they were read with a bare
`open`: first the READER, then the COMPRESSION, and never the other way
around.

ONE point of opening: every caller that used to do ``path.open(...)`` or
``path.read_text(...)`` on one of these files now goes through
``open_snapshot``/``read_snapshot_text`` instead — try the raw path, and
ONLY if it is absent, open the same path with a ``.gz`` suffix through
``gzip.open``. Never both, never a silent choice between stale copies: a
snapshot is either raw or gzipped, not two truths at once (the janitor
itself enforces this — see ``tools/snapshot_janitor.py``'s atomic
compress-then-remove).

Every open here also dates the snapshot with a last-access marker (one
empty sentinel file, mtime = last read) — the ONLY signal the janitor
trusts for "has anyone read this in the last N hours" before it gzips a
directory. A read one second before the janitor's sweep buys a fresh
reprieve; a read is not just tolerated during the idle window, it is what
DEFINES the window.

🔴 BUT THE MARKER LIVES OUTSIDE, AND AS OF 2026-09-07 THIS IS AN OWNER'S
DECISION, NOT A DETAIL. Before this date `touch_last_access` put
`.last_access` INSIDE the decompile directory ITSELF — and thereby THE READ
CHANGED WHAT WAS BEING READ. The cost of this was measured three times in
different places in the tree, and each time ONE copy was fixed:

* `capture_edit.open_capture` promises in its docstring "the directory is
  READ ONLY" — and dropped the marker there anyway; the pin
  `test_a_capture_refuses_by_name_not_by_traceback` had to forgive it with
  a dedicated line;
* `clash/existing.py` (08-21) — the resolver read the passport of EVERY
  candidate, creating the file moved the DIRECTORY's mtime, and freshness,
  which decides as the third key, became identical for all of them: the
  first one alphabetically won;
* `viewer/cache.py` (08-11) — the marker made it into the scene key's
  inputs, and the cache stopped hitting FOREVER for anyone who opened the
  comparison.

Hence the carrier is single and external: `KIR_CACHE_HOME` -> `XDG_CACHE_HOME` ->
`~/.cache`, then `kir/lift/<sha256 of the directory's realpath>`. Next to the
marker sits the PROVENANCE (`path` — the path itself as text): the key is
unreadable, and without it the journal would be a pile of hexadecimal names
that can neither be checked nor cleaned up by hand.

The janitor (`kir/instruments/snapshot_janitor.py::last_access_ts`) reads
BOTH carriers and takes the MAXIMUM: decompiles taken before 2026-09-07
carry the old marker inside them, and it is their only protection from
gzip. Nothing is written inside anymore.
"""
from __future__ import annotations

import gzip
import hashlib
import os
from pathlib import Path
from typing import IO, Any, Iterable, Mapping

#: Sentinel filename; only its mtime matters. Written to the EXTERNAL JOURNAL
#: (`access_journal_dir`); inside the decompile directory it occurs only for
#: decompiles older than 2026-09-07 — and there the janitor reads it, but no one writes it.
LAST_ACCESS_MARKER = ".last_access"

#: Provenance next to the marker: the path THIS journal entry is ABOUT. The
#: key is a sha256, i.e. unreadable to a human; without this file the journal
#: could neither be checked nor cleaned up by hand.
ACCESS_PROVENANCE_NAME = "path"


def access_journal_root() -> Path:
    """Root of the external access journal.

    `KIR_CACHE_HOME` -> `XDG_CACHE_HOME` -> `~/.cache`, then `kir/lift`.
    The order is exactly this: the specific name overrides the general one,
    the general one overrides the default. An empty value of the variable is
    treated as NOT SET (`KIR_CACHE_HOME=` in the environment would otherwise
    send the journal to the filesystem root).
    """
    from kir import env as _env  # the single environment door (kir/env.py), not os.environ
    for name in ("KIR_CACHE_HOME", "XDG_CACHE_HOME"):
        raw = _env.get(name)
        if raw:
            return Path(raw) / "kir" / "lift"
    return Path(os.path.expanduser("~")) / ".cache" / "kir" / "lift"


def access_journal_key(directory: os.PathLike[str] | str) -> str:
    """Stable derivative of the directory's ABSOLUTE path.

    `realpath`, not the path itself: `data/x`, `./data/x` and a symlink to
    them are one and the same decompile, and three journal entries about one
    directory would mean that the reprieve bought by one reader is invisible
    to the second.
    """
    real = os.path.realpath(os.fspath(directory))
    return hashlib.sha256(real.encode("utf-8", "surrogateescape")).hexdigest()


def access_journal_dir(directory: os.PathLike[str] | str) -> Path:
    """The journal directory responsible FOR THIS decompile: marker + provenance."""
    return access_journal_root() / access_journal_key(directory)


def gz_path(path: Path) -> Path:
    """L0.jsonl -> L0.jsonl.gz — append, never replace, the suffix: several
    snapshot files (``curve.index.json``) already end in ``.json``, and
    ``Path.with_suffix`` would eat that, not extend it."""
    return path.with_name(path.name + ".gz")


def touch_last_access(directory: os.PathLike[str] | str) -> None:
    """Mark access to ``directory`` — IN THE EXTERNAL JOURNAL.

    🔴 NOTHING IS WRITTEN INTO THE DIRECTORY ITSELF (owner's decision of
    2026-09-07, the full argument is in the module header). Three places in
    the tree paid for the former carrier: `open_capture` promised "the
    directory is READ ONLY," the clash resolver lost the candidates'
    freshness, the viewer's scene key stopped hitting the cache.

    Never raises: a snapshot on read-only media, or one the janitor is
    mid-cleanup on, must not turn a read into a crash just because the
    bookkeeping write failed. The read itself already succeeded or failed
    on its own terms by the time this runs. The property is the SAME as
    before, only now it is the JOURNAL's failure that gets swallowed: it may
    be unavailable, sit on a read-only partition, or fail to be created at all.

    Provenance is written BEFORE the marker and only if it does not exist yet:
    a journal entry that has a marker and no path is unreadable, and
    rewriting it on every read would mean paying for an access mark with an
    extra `write`.
    """
    try:
        entry = access_journal_dir(directory)
        entry.mkdir(parents=True, exist_ok=True)
        provenance = entry / ACCESS_PROVENANCE_NAME
        if not provenance.exists():
            provenance.write_text(
                os.path.realpath(os.fspath(directory)) + "\n",
                encoding="utf-8", errors="surrogateescape")
        (entry / LAST_ACCESS_MARKER).touch(exist_ok=True)
    except (OSError, ValueError):
        pass


def snapshot_file_exists(path: os.PathLike[str] | str) -> bool:
    """True if the raw file OR its gzipped counterpart is on disk.

    Every caller that used to guard with ``path.is_file()`` (side-index
    loaders returning ``None`` for "this stage never ran") must ask this
    instead — a gzipped side index is not "absent", and treating it as one
    would silently degrade a real snapshot to an empty one.
    """
    path = Path(path)
    return path.is_file() or gz_path(path).is_file()


def open_snapshot(
    path: os.PathLike[str] | str,
    mode: str = "rb",
    *,
    encoding: str | None = None,
    touch: bool = True,
) -> IO[Any]:
    """Open a snapshot artifact: the raw ``path`` if it exists, else the
    same path + ``.gz`` through ``gzip.open`` — same call, same file-like
    return either way, so callers never branch on which one they got
    (``for line in handle`` and ``handle.read()`` both work on either).

    ``mode``/``encoding`` mean exactly what they mean for the builtin
    ``open`` (and ``gzip.open`` accepts the identical pair) — "rb" for
    ``L0JSONLReader``'s streaming binary parse, "rt"+encoding for the
    side-index loaders' whole-file JSON reads.
    """
    path = Path(path)
    if touch:
        touch_last_access(path.parent)
    kwargs: dict[str, Any] = {} if encoding is None else {"encoding": encoding}
    try:
        return path.open(mode, **kwargs)
    except FileNotFoundError:
        return gzip.open(gz_path(path), mode, **kwargs)


def read_snapshot_text(
    path: os.PathLike[str] | str,
    *,
    encoding: str = "utf-8",
    touch: bool = True,
) -> str:
    """Whole-file convenience over ``open_snapshot`` text mode — replaces
    the ``path.read_text(encoding=...)`` calls the side-index loaders
    (``_load_side_index``/``_load_envelope``) used to make directly."""
    with open_snapshot(path, "rt", encoding=encoding, touch=touch) as handle:
        return handle.read()


# ─────────────────────────────────────────────────────────────────────────────
# CONTENT IDENTITY: WHAT WAS IN THESE BYTES WHEN THEY WERE COMPRESSED
# ─────────────────────────────────────────────────────────────────────────────
#
# 🔴 WHY, MEASURED 2026-08-20 — AND THIS IS NOT WHAT THE JANITOR CHECKS TODAY.
#
# `snapshot_janitor._gzip_file_verified` compresses into a temporary file,
# reads it back, and compares it against the original BYTE FOR BYTE, and only
# then deletes the raw one. This is a sound and necessary check — but it is
# about the COMPRESSOR and lives for exactly one instant: after `unlink()`
# the single remaining copy is left without any witness to what it was.
#
# A FAIL control on a copy of the `graph_check` decompile showed the boundary
# precisely:
#
#     container corrupted   -> BadGzipFile "Unknown compression method" LOUDLY
#     content swapped       -> THE INSTRUMENT'S ANSWER DID NOT CHANGE AT ALL
#                              (wall thickness 200 -> 999; 1504 shells,
#                              52 refusals, the census digest the same)
#
# The second one is the hole: gzip protects against a broken container and
# does not protect against content drift. And comparing the SUMMARY is
# useless by construction — a swap that isn't reflected in the summary will
# never move it.
#
# Hence the carrier: a digest of the RAW bytes, recorded at the moment of
# compression, next to the files. It does not get in the janitor's way and
# does not replace its check — it extends that check through time.
DIGEST_MANIFEST = "snapshot.digests.json"
DIGEST_SCHEMA = "kir-snapshot-digests/1"


def digest_bytes(data: bytes) -> str:
    """SHA-256 of the raw bytes. One place so the algorithm cannot drift."""

    return hashlib.sha256(data).hexdigest()


def record_digest(directory: os.PathLike[str] | str, name: str,
                  data: bytes) -> None:
    """Record WHAT the file `name` was at the moment of compression.

    Called by the janitor RIGHT NEXT TO `_gzip_file_verified`, before the raw
    file's `unlink()`: the bytes are already read there, no second read is needed.

    The manifest is appended one name at a time and is NEVER overwritten
    wholesale: two files of the same decompile are compressed sequentially,
    and a full overwrite would lose the neighbor.
    """
    import json

    directory = Path(directory)
    path = directory / DIGEST_MANIFEST
    import tempfile

    rows: dict[str, Any] = {}
    lost: str | None = None
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("files"), dict):
                rows = loaded["files"]
        except (OSError, ValueError) as exc:
            # 🔴 PRIOR EVIDENCE IS LOST EXACTLY HERE, AND THIS MUST BE
            # VISIBLE (F-019). The previous edit set `rows = {}` and
            # published a manifest of just ONE new line; the next check
            # would find that line matching and print "0 discrepancies" for
            # a snapshot that no longer had a witness.
            #
            # The comment sitting here said "not a reason to silently discard
            # the old ones" — while the code discarded them exactly silently.
            # This was a direct mismatch between prose and body, and the body
            # was the one to trust.
            #
            # We keep the corrupted file alongside: it is the only evidence
            # of WHAT went bad. It does not get in the janitor's way — the
            # janitor walks `SNAPSHOT_FILES`, and this name is not in there.
            broken = path.with_suffix(path.suffix + ".broken")
            try:
                os.replace(path, broken)
            except OSError:
                pass
            rows = {}
            lost = "манифест был нечитаем и заведён заново: %s: %s" % (
                type(exc).__name__, exc)
    rows[str(name)] = {"sha256": digest_bytes(data), "bytes": len(data)}
    payload: dict[str, Any] = {"schema_version": DIGEST_SCHEMA, "files": rows}
    if lost is not None:
        payload["prior_rows_lost"] = lost
    # 🔴 THE TEMPORARY FILE'S NAME IS UNIQUE, NOT FIXED (E-14). The former
    # `<manifest>.tmp` was one name shared by every writer in the directory:
    # two concurrent `record_digest` calls would write into the same
    # temporary file, and `os.replace` would publish a half-finished result.
    # The same class as the confirmed `F-070` in the pipeline, only in a
    # different module.
    #
    # A unique name removes the FILE COLLISION and does NOT remove the LINE
    # LOSS: the "read-add-replace" sequence is still without a lock. Today
    # there is a single writer (the janitor, single-threaded), so the lock is
    # protection against a FUTURE parallel janitor and is addressed separately.
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(directory), delete=False,
        prefix=DIGEST_MANIFEST + ".", suffix=".tmp")
    try:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")))
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


def verify_digests(
    directory: os.PathLike[str] | str,
    *,
    expected: Iterable[str] | None = None,
) -> dict[str, str]:
    """Verify the stored files against the recorded digests.

    `expected` is the CLOSED list of names that must stand under a witness
    (F-343). Without it the behavior is byte-for-byte as before: the `None`
    default does not change a single existing call.

    Returns a dict `name -> reason` ONLY for discrepancies; an empty dict
    means "everything matched." A missing manifest is NEITHER a discrepancy
    NOR silence: it is a separate outcome `{"": "no manifest"}`, because
    "nothing to check" and "checked, everything matched" are different facts,
    and conflating them here would mean introducing exactly the silent zero
    this whole block is written against.
    """
    import json

    directory = Path(directory)
    path = directory / DIGEST_MANIFEST
    if not path.is_file():
        return {"": "манифеста нет — сверять не с чем"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"": "манифест не читается: %s" % exc}
    # 🔴 LEGITIMATE JSON OF A FOREIGN SHAPE CRASHED THE CHECKER (F-344). The
    # guarding `except` ended ONE LINE ABOVE, and `[]` or `"a string"` reached
    # `.get` already outside it: an `AttributeError` instead of a verdict. A
    # corrupted manifest must be a NAMED outcome of the check, not a crash of
    # its caller.
    if not isinstance(payload, Mapping):
        return {"": "манифест не словарь, а %s" % type(payload).__name__}
    if payload.get("schema_version") != DIGEST_SCHEMA:
        return {"": "чужая схема манифеста: %r" % payload.get("schema_version")}
    rows = payload.get("files")
    if not isinstance(rows, dict):
        return {"": "манифест без раздела files"}

    bad: dict[str, str] = {}
    # The mark about lost lines is set by `record_digest` (F-019); without
    # reading it, it would be a record no one ever asks about.
    lost = payload.get("prior_rows_lost")
    if lost:
        bad[DIGEST_MANIFEST] = str(lost)
    for name, row in sorted(rows.items()):
        target = directory / name
        if not snapshot_file_exists(target):
            bad[name] = "файла нет ни сырым, ни сжатым"
            continue
        try:
            with open_snapshot(target, "rb", touch=False) as handle:
                data = handle.read()
        except Exception as exc:                  # noqa: BLE001 — the disk seam
            bad[name] = "не читается: %s: %s" % (type(exc).__name__, exc)
            continue
        if not isinstance(row, Mapping):
            # `(row or {}).get(...)` returned `want = None` and printed
            # "content diverged" — blaming the FILE for damage to the MANIFEST.
            bad[name] = "строка манифеста не словарь, а %s" % type(row).__name__
            continue
        want = row.get("sha256")
        got = digest_bytes(data)
        if want != got:
            bad[name] = "содержимое разошлось: было %s, стало %s" % (
                str(want)[:16], got[:16])
    # 🔴 THE MANIFEST ANSWERS FOR ITS OWN ROWS, BUT IT IS READ AS IF FOR THE
    # SNAPSHOT (F-343). The loop above walks OVER THE MANIFEST'S ROWS: a file
    # that is not in the manifest is NEVER seen by it — which is why it can
    # say nothing about it. A directory with two snapshots and a
    # one-line manifest returned `{}`, i.e. "everything matched," in exactly
    # the case where less than half was checked.
    #
    # The list is supplied by the CALLER, not derived from the directory: the
    # directory also carries non-snapshot files (`status.json`, the manifest
    # itself, journals), and "what must stand under a witness" cannot be
    # derived from it — that would produce noise that gets muted wholesale,
    # guard included, within a week.
    for name in sorted(expected or ()):
        if name in rows:
            continue
        if snapshot_file_exists(directory / name):
            bad[name] = ("файл есть, а строки в манифесте нет — сверять "
                         "НЕЧЕМ: он либо сжат до появления манифеста, либо "
                         "строка потеряна")
    return bad

def snapshot_raw_size(path: os.PathLike[str] | str) -> int:
    """Size of the RAW snapshot in bytes — and exactly so for the compressed one too.

    🔴 WHY A SEPARATE FUNCTION. `os.path.getsize` on the raw name of a
    compressed decompile returns ZERO (no file), and any ceiling built on this
    size stops working SILENTLY: "zero bytes" passes any threshold. Caught
    2026-08-20 in `serving._building_index_for_turn` — there a zero would have
    meant "observations are cheap" on an 88 MB tower.

    The compressed size is not taken by estimate or coefficient: gzip stores
    the length of the original data in the LAST FOUR BYTES (ISIZE,
    little-endian). This is exact for files up to 4 GB; our snapshots are an
    order of magnitude smaller, and the boundary is named here, not implied.

    Zero is returned only if NEITHER the raw NOR the compressed file exists —
    that is, this is still "no file," and telling this case apart is the job
    of `snapshot_file_exists`, not of the value.
    """
    raw = Path(path)
    if raw.is_file():
        return raw.stat().st_size
    gz = gz_path(raw)
    if not gz.is_file():
        return 0
    try:
        with open(gz, "rb") as handle:
            handle.seek(-4, os.SEEK_END)
            return int.from_bytes(handle.read(4), "little")
    except OSError:
        return gz.stat().st_size
