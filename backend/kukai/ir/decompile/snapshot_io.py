"""Transparent gzip fallback for on-disk decompile snapshots.

A snapshot directory (``backend/data/decompile/<change_stamp>/``) holds
``L0.jsonl`` and the side indexes (``curve.index.json``, ``curtain.index
.json``, ``sketch.index.json``, ``family_placement.index.json``,
``group.index.json``) — the big, cold-once-a-run artifacts, 13-47MB raw
per document (2026-07-29 measurement). ``tools/snapshot_janitor.py`` gzips
these IN PLACE once a snapshot has gone quiet (``L0.jsonl`` -> ``L0.jsonl
.gz``, same name plus suffix, raw file removed) — gzip gets ~14x on this
corpus, and every reader must keep working unchanged afterwards.

ONE point of opening: every caller that used to do ``path.open(...)`` or
``path.read_text(...)`` on one of these files now goes through
``open_snapshot``/``read_snapshot_text`` instead — try the raw path, and
ONLY if it is absent, open the same path with a ``.gz`` suffix through
``gzip.open``. Never both, never a silent choice between stale copies: a
snapshot is either raw or gzipped, not two truths at once (the janitor
itself enforces this — see ``tools/snapshot_janitor.py``'s atomic
compress-then-remove).

Every open here also touches the snapshot directory's last-access marker
(one empty sentinel file, mtime = last read) — the ONLY signal the janitor
trusts for "has anyone read this in the last N hours" before it gzips a
directory. A read one second before the janitor's sweep buys a fresh
reprieve; a read is not just tolerated during the idle window, it is what
DEFINES the window.
"""
from __future__ import annotations

import gzip
import os
from pathlib import Path
from typing import IO, Any

#: Sentinel filename inside a snapshot directory; only its mtime matters.
LAST_ACCESS_MARKER = ".last_access"


def gz_path(path: Path) -> Path:
    """L0.jsonl -> L0.jsonl.gz — append, never replace, the suffix: several
    snapshot files (``curve.index.json``) already end in ``.json``, and
    ``Path.with_suffix`` would eat that, not extend it."""
    return path.with_name(path.name + ".gz")


def touch_last_access(directory: os.PathLike[str] | str) -> None:
    """Update (or create) ``directory``'s last-access marker.

    Never raises: a snapshot on read-only media, or one the janitor is
    mid-cleanup on, must not turn a read into a crash just because the
    bookkeeping write failed. The read itself already succeeded or failed
    on its own terms by the time this runs.
    """
    try:
        Path(directory, LAST_ACCESS_MARKER).touch(exist_ok=True)
    except OSError:
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
