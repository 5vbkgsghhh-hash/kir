"""Storage for the building's journal — the only wire `journal` has to
the outside.

`journal.py` can do everything the journal can do: the hash chain,
rollback, audit, deterministic replay of the state at any revision.
What it CANNOT do — know that yesterday's decompile and today's belong
to the same building, and where to put this journal. That was exactly
what was missing: 471 lines and 22 tests sat in storage with the
docstring's own note "opt-in gate for future pipeline wiring."

The gap being closed is named briefly: **the building had no
history**. On disk there are 52 folded decompiles, and by the
09.08.2026 measurement they group into 10 buildings by
`passport.json::doc_name` — the facade
`SOB6.2_UPO_L_DOO_FAS_R23_kuklev.d.s` has EIGHTEEN of them. The system
remembered neither that this was one building, nor what had changed
between two readings: to answer "what changed since last time" meant
holding both `tree.json` files and recomputing the diff from scratch.
The model, which needs `base_doc_stamp` for a delta reassembly, had
nowhere to take it from — only from the operator's memory.

This module computes NOTHING new. The delta is computed by
`journal.commit_trees` (and through it, `rebuild.delta_between`),
which also checks applicability; here there is only persistence and
reporting, between `journal` and its two consumers:

* `decompile/pipeline.py` — the live path: a decompile APPENDS a
  revision to its building's journal (flag `KUKAI_IR_JOURNAL`, OFF by
  default) and places next to `tree.json` a receipt `journal.json` of
  exactly what it appended;
* `ir/serving.py::handle_revit_rebuild` — the reader: a
  `base_doc_stamp` with the value `@journal` resolves to the PREVIOUS
  revision of the same building, and the resolved name travels in the
  response.

THE JOURNAL SITS NEXT TO THE DECOMPILES, not inside one of them:
`_journals/` in the directory where the run directories live. It is
shared across all revisions of a building — that is its whole point;
were it inside a run, "the previous decompile of the same building"
would again have to be found by brute-force search.

THE JOURNAL KEY IS THE DOCUMENT NAME, and it is ALWAYS accompanied by
a digest of the FULL name. A sanitizer with no digest would merge
"A B" and "A_B" into one file, i.e. would silently merge the histories
of two different buildings — the same lesson already recorded in
`serving._decompile_out_dir`.

A BOUNDARY THAT MUST BE NAMED, NOT HIDDEN: the `journal/1` hash chain
signs STATES and DELTAS — "what the building was and what changed in
it." The accompanying revision strings (`doc_stamp`, `out_dir`, time)
are not part of the chain and can be forged unnoticed. A substituted
delta is caught; a substituted signature's "where it came from" is
not.

AND A SECOND ONE, MEASURED: `doc_name` is a file name, not the
building's identity. Measured 09.08.2026 across 52 decompiles:
`k2_ar_rd_v6`/`v7` carry `13A-RD-AR-K2_v33`, while `k2_ar_rd_v8`
carries `13A-RD-AR-K2_v33_kuklev.d.s`, i.e. "save as" BREAKS the
journal, and the pair used to measure delta reassembly would have
landed in two different logs. This is not a silent merge (the two
histories do not mix), but it is a lost link, and the warning about it
travels in the receipt: `previous_doc_stamp: null` with a non-empty
decompile directory means exactly "a building under this name is
being read for the first time."
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from kir.decompile.journal import (
    JOURNAL_VERSION,
    BuildingJournal,
    JournalError,
    commit_trees,
    new_journal,
)

LOG_SCHEMA = "kir-building-log/1"
REPORT_SCHEMA = "kir-journal-report/1"

#: The directory of shared journals, next to the run directories.
LOG_DIRNAME = "_journals"

__all__ = [
    "LOCK_SUFFIX",
    "LOG_DIRNAME",
    "LOG_SCHEMA",
    "REPORT_SCHEMA",
    "JournalBusy",
    "building_key",
    "history_report",
    "load_log",
    "lock_path",
    "log_path",
    "previous_stamp",
    "record_revision",
]


# ---------------------------------------------------------------------------
# Key and path
# ---------------------------------------------------------------------------


def building_key(doc_name: str) -> str:
    """The journal file name for document `doc_name`.

    A digest of the full name is appended ALWAYS, not only when the
    sanitizer damaged something: two documents differing only in a
    character the sanitizer collapses must get different files. The
    readable prefix stays only so the `_journals/` directory can be
    understood by eye.
    """

    name = doc_name if isinstance(doc_name, str) else ""
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    safe = "".join(
        ch if (ch.isalnum() or ch in "-_.") else "_" for ch in name)
    prefix = safe.strip("._")[:80] or "document"
    return f"{prefix}-{digest}"


def log_path(root: str | os.PathLike[str], doc_name: str) -> Path:
    """`<root>/_journals/<key>.json` — the journal of ONE building."""

    return Path(root) / LOG_DIRNAME / f"{building_key(doc_name)}.json"


def absent_log_may_hide_history(root: str | os.PathLike[str],
                                doc_name: str) -> str | None:
    """`None` if "there is no journal" honestly means "the building is
    being read for the first time"; otherwise the REASON this
    conclusion is doubtful.

    🔴 A COMPANION TO `load_log`. That one returns `None` for EXACTLY
    "no file"; corruption raises `JournalError`, and that distinction
    is already made. But `None` itself carries two different
    meanings, and they cannot be told apart from inside the file:

        the building is being decompiled for the FIRST TIME -> there
        never was a journal, all correct
        the journal was LOST (deleted, wrong root,
        the document renamed)  -> the building's history existed

    The second is visible from OUTSIDE: if decompiles of this same
    building exist in the corpus, but there is no journal, then
    "no revisions" is a claim about the MACHINE. A run will start a
    new journal at revision 0, and the operator will read "history
    just began," when in fact it was interrupted.

    `load_log`'s answer does not change: a journal record must not be
    dropped on mere suspicion, and "for the first time" remains a
    legal outcome.
    """
    # No root — no decompiles either, nothing to suspect: an empty
    # walk says so itself, and a separate "no root" branch is not
    # needed here at all.
    base = Path(root)
    same: list[str] = []
    for entry in sorted(base.iterdir()) if base.is_dir() else ():
        # 🔴 THE SKIP HERE IS MUTE, AND THIS IS A DECISION RECORDED IN
        # THE MUTENESS JOURNAL. Non-directories and the service
        # `_journals`/`_evidence` do not pretend to be decompiles: no
        # one promised a source here, and complaining about them would
        # be noise, not a guard. I rewrote this spot twice, chasing a
        # shape the scanner would not notice — that would have been
        # gaming the instrument, not fixing it. The spot is entered
        # into MUTE_SOURCES with its reasoning.
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        # A directory with no passport is not a decompile, and the
        # skip here is DELIBERATELY SILENT: complaining about service
        # directories would mean creating noise instead of a guard.
        #
        # 🔴 THROUGH `snapshot_file_exists` AND `open_snapshot`, NOT A
        # BARE `is_file`/`read_text` — AND THIS IS BOUGHT BY A
        # MEASUREMENT ON THE LIVE CORPUS OF 29.08.2026, THE DAY THIS
        # FUNCTION WAS WRITTEN:
        #
        #     decompiles                                    93
        #     with passport.json                            11
        #     with passport.json.gz                         45
        #     NOT VISIBLE to a bare is_file(passport.json)  82
        #
        # The janitor compresses side files IN PLACE, and a compressed
        # passport looks ABSENT to a bare reader. The function set up
        # to tell "the building is being decompiled for the FIRST
        # TIME" apart from "the journal was LOST" would find no
        # evidence for 82 of 93 decompiles and would say "first time"
        # — i.e. it would give exactly the false answer it was written
        # against, and the louder the OLDER the corpus: cooled-down
        # decompiles are precisely the compressed ones.
        #
        # Asking about compression and then reading raw is half the
        # trouble: `read_text` on a `.gz` would hand binary garbage to
        # `json.loads`. Whoever asks through the helper reads through
        # it too.
        from kir.decompile.snapshot_io import (open_snapshot,
                                               snapshot_file_exists)

        passport = entry / "passport.json"
        if snapshot_file_exists(passport):
            try:
                with open_snapshot(passport, "rt", encoding="utf-8",
                                   touch=False) as handle:
                    name = json.loads(handle.read()).get("doc_name")
            except (OSError, ValueError):
                name = None
            if name == doc_name:
                same.append(entry.name)
    if not same:
        return None
    return (f"журнала здания нет, но разборы того же документа в корпусе ЕСТЬ "
            f"({len(same)}: {', '.join(same[:3])}"
            f"{', …' if len(same) > 3 else ''}). «Ревизий нет» здесь может быть "
            f"фактом о МАШИНЕ — журнал снесён, переименован документ либо взят "
            f"не тот корень. Прогон заведёт историю заново с revision 0")


# ---------------------------------------------------------------------------
# THE JOURNAL LOCK
# ---------------------------------------------------------------------------
#
# 🔴 WHAT IS CLOSED HERE (RV-11). `record_revision` is a
# READ-COMPUTE-REPLACE: it reads the journal's head, computes a delta
# from it, and swaps the file via `os.replace`. The swap is atomic,
# but the whole triple is not, and there is a window between the read
# and the swap. Measured before the fix, two revisions of one
# building written at the same time:
#
#     CONTROL    sequential : r1.rev=1  r2.rev=2  events in journal = 3
#     EXPERIMENT parallel   : A={ok, rev=1}  B={ok, rev=1}  events = 2
#
# BOTH got SUCCESS and THE SAME revision; one piece of work vanished
# silently. This is the worst kind of loss: the journal exists so the
# building has a history, and a history with a hole in it looks
# exactly like an honest one — the same reasoning by which a corrupted
# log here REFUSES, rather than starting over.
#
# WHY A FILE LOCK SPECIFICALLY, NOT `threading.Lock`. The journal is a
# FILE, and its writers are not only threads of one process.
# `record_revision` is called from the pipeline through `_offload`
# (its own thread), and the pipeline itself runs in the backend, which
# on this machine comes up as separate units, and a decompile is also
# launched by hand from another interpreter. An in-process memory lock
# is not visible to a neighboring process at all — it would close
# exactly the case that is easiest to reproduce and leave open the one
# that costs the most.
#
# `flock` (POSIX) and `msvcrt.locking` (Windows) were chosen because
# the lock is held by the KERNEL: a dead process releases it by
# itself, and no cleanup of stale locks is needed. A marker file
# (`O_CREAT|O_EXCL`) cannot do this — a crashed writer would lock the
# building's journal forever, and fixing that would require a
# heuristic on file age, i.e. a guess.
#
# A platform with neither mechanism REFUSES, rather than writing
# silently: "no lock" and "lock taken" must look different to whoever
# reads the receipt.
#
# THE READER (`load_log`) needs no lock: `os.replace` is atomic, and
# the reader sees either the whole old file or the whole new one.

#: The tail of the lock file's name, next to the journal. Not
#: `*.json`, so scans of the `_journals/` directory (`viewer.history`,
#: tests) do not pick it up.
LOCK_SUFFIX = ".lock"

#: How long to wait for someone else's write. Longer than that is a
#: HONEST REFUSAL: "busy" and "written" must look different, and an
#: infinite wait looks like work.
LOCK_TIMEOUT_S = 30.0
_LOCK_POLL_S = 0.02

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - a non-POSIX platform
    _fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - an unrecognized platform
    _msvcrt = None  # type: ignore[assignment]

#: The name of the mechanism taken — so a refusal can name itself,
#: rather than say "it didn't work."
LOCK_MECHANISM = ("flock" if _fcntl is not None
                  else "msvcrt" if _msvcrt is not None else "none")


class JournalBusy(JournalError):
    """The journal is busy with another writer (or there is nothing to
    lock with).

    A separate kind exists precisely so that "didn't finish writing
    because busy" does not get mixed up with "didn't finish writing
    because the journal is corrupted": the first is fixed by a retry,
    the second by hand.
    """


def lock_path(path: str | os.PathLike[str]) -> Path:
    """The lock file next to the journal: `<journal>.json.lock`."""

    file_path = Path(path)
    return file_path.with_name(file_path.name + LOCK_SUFFIX)


def _try_take(descriptor: int) -> bool:
    if _fcntl is not None:
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError:
            return False
        return True
    take = getattr(_msvcrt, "locking")
    try:
        take(descriptor, _msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _release(descriptor: int) -> None:
    # Closing the descriptor would release the lock on its own too; we
    # release it explicitly so the order is visible, rather than
    # inferred from someone else's semantics.
    try:
        if _fcntl is not None:
            _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        elif _msvcrt is not None:
            _msvcrt.locking(descriptor, _msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextmanager
def _log_lock(path: Path, *, timeout: float | None = None) -> Iterator[None]:
    """Hold journal `path` for the duration of read-compute-replace.

    DO NOT RE-ENTER: the lock is taken on a new descriptor every time,
    and a nested entry from the same thread would lock itself out.
    Today there is one caller (`record_revision`), and there is no
    nesting.

    The timeout is read FROM THE MODULE at call time, not taken as a
    default value at declaration: otherwise checking the busy-refusal
    could only be done with a thirty-second test, i.e. not at all.
    """

    if timeout is None:
        timeout = LOCK_TIMEOUT_S
    # pragma: no cover - we have no platform with neither mechanism
    if LOCK_MECHANISM == "none":  # pragma: no cover
        raise JournalBusy(
            "межпроцессного замка на этой платформе нет (ни fcntl, ни "
            "msvcrt); дописывать журнал без него значило бы терять ревизии "
            "молча")
    lock = lock_path(path)
    # 🔴 THE LOCK IS OPENED FOR READING WHERE THAT IS ENOUGH. `flock`
    # does not require write rights (flock(2): "regardless of the mode
    # in which the file was opened"), and this is not a trifle: the
    # journal is SHARED for the building, and a decompile is launched
    # both by the service and by the operator — under different users.
    # Were we to require `O_RDWR`, the second one would run into the
    # 0644 left by the first and get a `PermissionError` instead of a
    # lock. The Windows mechanism does require write rights — there we
    # open for writing.
    flags = os.O_CREAT | (os.O_RDONLY if _fcntl is not None else os.O_RDWR)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(lock), flags, 0o666)
    except OSError as exc:
        # A typed refusal, not a bare exception thrown outward: the
        # caller must read the reason in the receipt.
        raise JournalBusy(f"файл-замок {lock} не открыть: {exc}") from exc
    try:
        deadline = time.monotonic() + timeout
        while not _try_take(descriptor):
            if time.monotonic() >= deadline:
                raise JournalBusy(
                    f"журнал {path} занят другим пишущим дольше "
                    f"{timeout:g} с (замок {LOCK_MECHANISM}: {lock})")
            time.sleep(_LOCK_POLL_S)
        try:
            yield
        finally:
            _release(descriptor)
    finally:
        os.close(descriptor)


# ---------------------------------------------------------------------------
# Reading / writing
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False,
        prefix=path.name + ".", suffix=".tmp")
    try:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


def load_log(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Read the building's journal; `None` — there is no file.

    An absent file and an UNREADABLE file are different facts, and
    they stay different here: a corrupted or forged journal raises
    `JournalError`, not `None`. Otherwise "the journal is broken"
    would become indistinguishable from "the building is being read
    for the first time," and the next run would start a new journal
    on top of the broken one, erasing the evidence.
    """

    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JournalError(f"журнал {file_path} не читается: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema") != LOG_SCHEMA:
        raise JournalError(
            f"журнал {file_path}: схема не {LOG_SCHEMA}")
    revisions = payload.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        raise JournalError(f"журнал {file_path}: нет ни одной ревизии")
    # `from_dict` calls `verify()` itself — the chain is checked on
    # EVERY read, not only on write.
    journal = BuildingJournal.from_dict(payload["journal"])
    if len(journal) != len(revisions):
        raise JournalError(
            f"журнал {file_path}: {len(revisions)} сопроводительных строк "
            f"против {len(journal)} событий цепочки")
    return dict(payload)


def journal_of(log: Mapping[str, Any]) -> BuildingJournal:
    """Parse the journal from the log (with chain verification)."""

    return BuildingJournal.from_dict(log["journal"])


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _refusal(exc: BaseException, **extra: Any) -> dict[str, Any]:
    """A refusal that is visible. Never pretends to be an empty history."""

    return {
        "schema": REPORT_SCHEMA,
        "journal_version": JOURNAL_VERSION,
        "ok": False,
        "appended": False,
        "error": {"type": type(exc).__name__, "message": str(exc)},
        **extra,
    }


def _delta_summary(journal: BuildingJournal, revision: int) -> dict[str, Any]:
    event = journal.changes_at(revision)
    delta = event.delta
    return {
        "touched": delta.touched_count,
        "emitted": delta.emitted_count,
        "retired": delta.retired_count,
        "relocated": delta.relocated_count,
        "reused": delta.reused_count,
        "summary": list(event.summary),
    }


def history_report(log: Mapping[str, Any]) -> dict[str, Any]:
    """The building's history: revisions, what changed at each, whether
    the chain is intact."""

    try:
        journal = journal_of(log)
    except (JournalError, KeyError, TypeError, ValueError) as exc:
        return _refusal(exc, doc_name=log.get("doc_name"))

    rows: list[dict[str, Any]] = []
    for row in log["revisions"]:
        index = int(row["revision"])
        entry = {
            "revision": index,
            "doc_stamp": row.get("doc_stamp"),
            "out_dir": row.get("out_dir"),
            "recorded_at": row.get("recorded_at"),
            "revit_version": row.get("revit_version"),
            "leaves": row.get("leaves"),
            "event_hash": journal.events[index].event_hash,
        }
        if index > 0:
            entry["delta"] = _delta_summary(journal, index)
        rows.append(entry)
    return {
        "schema": REPORT_SCHEMA,
        "journal_version": JOURNAL_VERSION,
        "ok": True,
        "appended": False,
        "doc_name": log.get("doc_name"),
        "key": log.get("key"),
        "head_revision": journal.head_revision,
        "revisions_total": len(journal),
        "head_hash": journal.events[-1].event_hash,
        "revisions": rows,
    }


def previous_stamp(
    log: Mapping[str, Any], doc_stamp: str,
) -> tuple[str | None, str | None]:
    """The revision stamp BEFORE `doc_stamp` in this journal.

    Returns `(stamp, refusal_reason)`. Takes the LAST occurrence of
    the stamp: the same `doc_stamp` can be reread, and "previous"
    means previous in the journal, not the first historical one.
    """

    revisions = list(log.get("revisions") or ())
    found = None
    for row in revisions:
        if row.get("doc_stamp") == doc_stamp:
            found = int(row["revision"])
    if found is None:
        return None, "not_in_journal"
    if found == 0:
        return None, "is_base_revision"
    return str(revisions[found - 1].get("doc_stamp") or ""), None


# ---------------------------------------------------------------------------
# Recording a revision — the very thing a live decompile calls
# ---------------------------------------------------------------------------


def _row(
    *, revision: int, doc_stamp: str, out_dir: str, revit_version: str,
    leaves: int, event_hash: str,
) -> dict[str, Any]:
    return {
        "revision": revision,
        "doc_stamp": doc_stamp,
        "out_dir": out_dir,
        "revit_version": revit_version,
        "leaves": leaves,
        "recorded_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "event_hash": event_hash,
    }


def _leaf_count(tree: Any) -> int:
    from kir.decompile.fold import iter_l1_leaves
    return sum(1 for _ in iter_l1_leaves(tree))


def record_revision(
    root: str | os.PathLike[str],
    *,
    doc_name: str,
    doc_stamp: str,
    out_dir: str,
    tree: Any,
    revit_version: str = "",
) -> dict[str, Any]:
    """Append this decompile to its building's journal; return a receipt.

    A building's first decompile starts the journal with a BASE
    revision (a state, no delta). Every next one reads the head
    revision's `tree.json` and calls `commit_trees`, which itself
    refuses if this tree does not reproduce the head's state — i.e. if
    the journal and the decompiles have drifted apart.

    No refusal ever restarts the journal from scratch or appends an
    "approximately right" revision: a journal that once received a lie
    is worse than a missing one, because it looks identical to an
    honest one.

    🔴 THE WHOLE "read-compute-replace" TRIPLE RUNS UNDER AN
    INTERPROCESS LOCK (RV-11, the reasoning is at `_log_lock` above).
    Two concurrent calls get EITHER two different revisions, OR one of
    them gets a `log_busy` refusal; "both succeed, but it's one
    revision" is an outcome this function can no longer produce.
    """

    base = {
        "schema": REPORT_SCHEMA,
        "journal_version": JOURNAL_VERSION,
        "doc_name": doc_name,
        "key": building_key(doc_name),
        "doc_stamp": doc_stamp,
    }
    path = log_path(root, doc_name)
    try:
        with _log_lock(path):
            return _append_revision(
                root, base=base, path=path, doc_name=doc_name,
                doc_stamp=doc_stamp, out_dir=out_dir, tree=tree,
                revit_version=revit_version)
    except JournalBusy as exc:
        # The refusal IS VISIBLE and named: a silent "ok" here was
        # exactly the defect.
        return _refusal(exc, **base, log_path=str(path), reason="log_busy")


def _append_revision(
    root: str | os.PathLike[str],
    *,
    base: dict[str, Any],
    path: Path,
    doc_name: str,
    doc_stamp: str,
    out_dir: str,
    tree: Any,
    revit_version: str = "",
) -> dict[str, Any]:
    """The body of `record_revision`. Called ONLY from under `_log_lock`."""

    try:
        log = load_log(path)
    except (JournalError, KeyError, TypeError, ValueError) as exc:
        # A corrupted/forged journal is a REFUSAL, not "let's start a
        # new one": overwriting would erase exactly the evidence the
        # chain exists for.
        return _refusal(exc, **base, log_path=str(path),
                        reason="log_unreadable")

    try:
        leaves = _leaf_count(tree)
    except (KeyError, TypeError, ValueError) as exc:
        return _refusal(exc, **base, log_path=str(path),
                        reason="tree_unreadable")

    if log is None:
        try:
            journal = new_journal(tree)
        except (JournalError, KeyError, TypeError, ValueError) as exc:
            return _refusal(exc, **base, log_path=str(path),
                            reason="base_not_foldable")
        rows = [_row(revision=0, doc_stamp=doc_stamp, out_dir=str(out_dir),
                     revit_version=revit_version, leaves=leaves,
                     event_hash=journal.events[0].event_hash)]
        _write(path, doc_name, journal, rows)
        # 🔴 "FIRST TIME" AND "THE JOURNAL WAS LOST" PRODUCE THE SAME
        # revision 0. They cannot be told apart from inside the file —
        # but from outside it is visible: decompiles of the same
        # building in the corpus. The suspicion travels IN THE
        # RESPONSE, not into the log.
        _maybe_lost = absent_log_may_hide_history(root, doc_name)
        return {
            **base, "ok": True, "appended": True, "log_path": str(path),
            "revision": 0, "head_revision": 0, "revisions_total": 1,
            "kind": "base", "leaves": leaves,
            **({"history_may_be_lost": _maybe_lost} if _maybe_lost else {}),
            "previous_doc_stamp": None,
            "head_hash": journal.events[0].event_hash,
        }

    rows = list(log["revisions"])
    head_row = rows[-1]
    head_stamp = str(head_row.get("doc_stamp") or "")
    if head_stamp == doc_stamp:
        # The same stamp reread again: this is not a new revision of
        # the building, but a repeated reading of the same one.
        # Appending an empty delta would mean cluttering the history
        # with events that never happened.
        journal = journal_of(log)
        return {
            **base, "ok": True, "appended": False, "log_path": str(path),
            "reason": "already_head",
            "revision": journal.head_revision,
            "head_revision": journal.head_revision,
            "revisions_total": len(journal),
            "previous_doc_stamp": (
                str(rows[-2].get("doc_stamp")) if len(rows) > 1 else None),
            "head_hash": journal.events[-1].event_hash,
        }

    head_tree_path = Path(str(head_row.get("out_dir") or "")) / "tree.json"
    # 🔴 THROUGH `snapshot_io`: `tree.json` has been compressed by the
    # janitor since 21.08.2026, and a bare `is_file()` on a cooled-down
    # head revision would give "no tree" — a refusal honest in form,
    # false in substance.
    from kir.decompile.snapshot_io import (
        read_snapshot_text, snapshot_file_exists)
    if not snapshot_file_exists(head_tree_path):
        return _refusal(
            FileNotFoundError(
                f"дерева головной ревизии нет: {head_tree_path}"),
            **base, log_path=str(path), reason="head_tree_missing",
            head_doc_stamp=head_stamp)
    try:
        head_tree = json.loads(
            read_snapshot_text(head_tree_path, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _refusal(exc, **base, log_path=str(path),
                        reason="head_tree_unreadable",
                        head_doc_stamp=head_stamp)

    try:
        journal = journal_of(log)
        # `commit_trees` will refuse on its own if `head_tree` does not
        # reproduce the head's state: the run directory could have
        # been overwritten by another building under the same stamp,
        # and the delta would be computed from a foreign base.
        journal = commit_trees(journal, head_tree, tree)
    except (JournalError, KeyError, TypeError, ValueError) as exc:
        return _refusal(exc, **base, log_path=str(path),
                        reason="not_applicable_to_head",
                        head_doc_stamp=head_stamp)

    revision = journal.head_revision
    rows.append(_row(
        revision=revision, doc_stamp=doc_stamp, out_dir=str(out_dir),
        revit_version=revit_version, leaves=leaves,
        event_hash=journal.events[revision].event_hash))
    _write(path, doc_name, journal, rows)
    return {
        **base, "ok": True, "appended": True, "log_path": str(path),
        "revision": revision, "head_revision": revision,
        "revisions_total": len(journal), "kind": "delta", "leaves": leaves,
        "previous_doc_stamp": head_stamp,
        "head_hash": journal.events[revision].event_hash,
        "delta": _delta_summary(journal, revision),
    }


def _write(
    path: Path, doc_name: str, journal: BuildingJournal,
    rows: list[dict[str, Any]],
) -> None:
    _atomic_write_json(path, {
        "schema": LOG_SCHEMA,
        "journal_version": JOURNAL_VERSION,
        "doc_name": doc_name,
        "key": building_key(doc_name),
        "revisions": rows,
        "journal": journal.to_dict(),
    })
