"""Snapshot janitor: gzip idle decompile snapshots, retire old revisions of
the same document, delete abandoned ones — offline, dry-run by default.

    python tools/snapshot_janitor.py                    # print the plan
    python tools/snapshot_janitor.py --apply             # execute it
    python tools/snapshot_janitor.py --root DIR --apply

A snapshot is one directory under ``backend/data/decompile/`` — the output
of one pipeline run (``kukai/ir/decompile/pipeline.py``). 2026-07-29
measurement: 13-47MB raw per snapshot (``L0.jsonl`` dominates), gzip gets
~14x on this corpus, 70GB free — the corpus grows one snapshot per run and
nothing has ever shrunk it.

Three rules, in order of precedence (a snapshot gets AT MOST one action):

1. RETENTION. Group snapshots by ``document_fingerprint`` (the SAME
   Revit document captured across many runs — v1..v13-style directories
   are the common case). Keep the ``KEEP_REVISIONS`` most recent per group
   (by ``status.json``'s own ``updated_at``, never by directory name or
   mtime, which a copy/restore can reset); delete the rest ENTIRELY.
2. INACTIVE DELETE. A snapshot untouched (see last_access below) for more
   than ``INACTIVE_DELETE_DAYS`` is deleted entirely, independent of the
   retention count (this is what reclaims a single, never-revisited
   one-off capture that retention alone would never touch — it is the
   only "2" of its own fingerprint group forever).
3. IDLE GZIP. A snapshot untouched for more than ``IDLE_HOURS`` gets its
   L0.jsonl + side indexes gzipped in place (raw removed only after the
   gzip readback is verified byte-identical) — every reader
   (``kukai/ir/decompile/snapshot_io.py``) already knows to fall back to
   the ``.gz`` counterpart, so nothing downstream needs to change.

"Untouched" is the ``.last_access`` marker
(``kir.decompile.snapshot_io.touch_last_access`` — every snapshot reader
dates it), falling back to ``status.json``'s ``updated_at`` for a snapshot
no reader has opened since it was written.

🔴 У МЕТКИ ДВА НОСИТЕЛЯ, И ЧИТАЮТСЯ ОБА (07.09.2026). Решением владельца
`touch_last_access` перестал писать метку ВНУТРЬ каталога разбора — чтение
не вправе менять читаемое — и пишет её теперь во ВНЕШНИЙ ЖУРНАЛ
(``KIR_CACHE_HOME`` / ``XDG_CACHE_HOME`` / ``~/.cache``, дальше
``kir/lift/<sha256 от realpath>``; см. ``snapshot_io.access_journal_dir``).
Разборы, снятые ДО этой даты, несут метку ВНУТРИ, и она их единственная
защита от gzip'а; читать только новый носитель значило бы объявить весь
исторический корпус «никем не читанным» разом. Поэтому ``last_access_ts``
берёт МАКСИМУМ двух носителей. Внутрь каталога не пишет больше никто.

IRON-CLAD, checked before any of the three rules and overriding all of
them:

* ``L0.checkpoint.json`` missing or ``footer_written`` is not ``true``
  (L0 extraction itself is unfinished) -> never touch.
* ``status.json`` missing or ``stage`` != ``"done"`` (the pipeline has not
  reached its own end) -> never touch.
* any ``a5_runs/*.state.jsonl`` journal whose last recorded phase is not
  ``"Completed"`` (an A5 rebuild/compare/cleanup cycle is mid-flight) ->
  never touch.
* younger than ``MIN_AGE_HOURS`` (by ``status.json.updated_at``, or by
  directory mtime if that is unavailable) -> never touch, regardless of
  the checks above (a run that finished ninety seconds ago should survive
  a script bug in the other three checks too).

All four thresholds are constants with an env override, the same
discipline ``EXTRACT_BATCH`` uses (``kukai/ir/decompile/schema.py``).
"""
from __future__ import annotations

import argparse
import dataclasses
import gzip
import json
import os
from kir import env  # noqa: E402  (submodule without dependencies — creates no cycles)
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The reader and the snapshot's WITNESS live in one place: the cleaner
# writes the manifest with the same functions that `--verify` later reads
# it with. A second instance of the digest algorithm would be exactly our
# named defect.
from kir.decompile.snapshot_io import (  # noqa: E402
    LAST_ACCESS_MARKER, access_journal_dir, gz_path, record_digest,
    verify_digests,
)
from kir.decompile.snapshot_pins import (  # noqa: E402
    pin_reason, pinned_snapshots, scan_reach,
)

# ── constants, env-overridable — KIR_SNAPSHOT_JANITOR_*, same
#    discipline as EXTRACT_BATCH (kukai/ir/decompile/schema.py) ────────────


def _env_float(name: str, default: float) -> float:
    return max(0.0, float(env.get(name, default)))


def _env_int(name: str, default: int) -> int:
    return max(0, int(env.get(name, default)))


#: A snapshot with no read in this many hours is eligible for gzip.
IDLE_HOURS = _env_float("KIR_SNAPSHOT_JANITOR_IDLE_HOURS", 6.0)
#: Nothing younger than this is EVER touched, no matter what the other
#: checks say — the last line of defense against a fresh run.
MIN_AGE_HOURS = _env_float("KIR_SNAPSHOT_JANITOR_MIN_AGE_HOURS", 1.0)
#: Revisions of one document (by document_fingerprint) kept; older ones
#: are deleted entirely.
KEEP_REVISIONS = _env_int("KIR_SNAPSHOT_JANITOR_KEEP_REVISIONS", 2)
#: A snapshot with no read in this many days is deleted entirely,
#: regardless of how many revisions of its document exist.
INACTIVE_DELETE_DAYS = _env_float(
    "KIR_SNAPSHOT_JANITOR_INACTIVE_DELETE_DAYS", 30.0)

#: 🔴 HOW MANY DAYS OF SILENCE UNLOCK COMPRESSION FOR A "LIVE" SNAPSHOT.
#:
#: The iron-clad guard `check_live` fails toward the safe SIDE: no
#: `status.json` with `stage=done` — the run is considered incomplete.
#: The 21.08 measurement showed the price of this correct strictness: 42
#: snapshots out of 88 are left untouched, holding 1.2 GB of compressible
#: data. The reason is the same for all of them — the control files DO
#: NOT EXIST AT ALL: they were written by a different pipeline than the
#: current one. The guard does not distinguish "incomplete" from "written
#: by the old pipeline".
#:
#: TIME distinguishes them. A decompile in progress writes continuously;
#: a directory where not a single file has changed in a week cannot be in
#: progress. So a relaxation is granted:
#:   * ONLY for compression. Deletion remains iron-clad: a compression
#:     error costs CPU time, a deletion error costs the only copy;
#:   * ONLY for files that are not being APPENDED TO (see APPEND_TARGETS).
#:     A resumed extraction appends to `L0.jsonl` with the raw writer, and
#:     next to `L0.jsonl.gz` a second truth would appear — exactly what
#:     `snapshot_io` forbids: a snapshot is either raw or compressed.
SILENT_DAYS_FOR_GZIP = _env_float(
    "KIR_SNAPSHOT_JANITOR_SILENT_DAYS_FOR_GZIP", 7.0)

#: 🔴 `updated_at` CANNOT BE EARLIER THAN THIS MARK: the decompile corpus
#: did not exist before it. The number is ASSIGNED, and this is stated
#: plainly — it is not a measurement but a lower bound of plausibility,
#: and it is needed so that `0` and `1` are not read as "a snapshot from
#: 1970". 2025-01-01 UTC is taken with more than a year of margin: moving
#: the bound up later is cheaper than explaining a deleted snapshot.
#:
#: The risk is stated plainly: a snapshot HONESTLY dated before
#: 2025-01-01 will become "age unknown" and will never be deleted. There
#: are none such in the corpus (measurement of 29.08.2026: all 91 found
#: `updated_at` values are of type `float`, 0 invalid, the oldest mark is
#: 1784631766.09 = 2026-07-21), and the price of an error in this
#: direction is an extra gigabyte, not lost data.
MIN_PLAUSIBLE_UPDATED_AT = 1735689600.0

#: The exact files snapshot_io.py's shim covers — gzip touches only these.
#:
#: 🔴 SIX -> TEN, 21.08.2026, AND THIS IS NOT A "WHILE WE'RE AT IT"
#: EXTENSION. Measurement on the corpus (`backend/data/decompile`, 5.0 GB,
#: disk at 84%): the largest names — `L0.jsonl` 1029 MB (already
#: compressed), `passport.json` 1001 MB, `named.json` 422 MB, `tree.json`
#: 416 MB, `verify.json` 342 MB. That is, 2.18 GB, TWICE everything the
#: cleaner previously knew how to touch, lay out of reach — for exactly
#: one reason: they were read with a bare `open`, not through
#: `snapshot_io`.
#:
#: The order was exactly this and remains law: a name enters here AFTER
#: every one of its readers has been run through the shim, not before.
#: Compressing earlier would have meant blinding the reader silently —
#: the very same named defect where "two shelves covered up each other's
#: defects".
#:
#: `named.json`, one of the four new ones, is a special case named by a
#: number: it has ZERO readers in prod (only `pipeline.py` writes it and
#: tests check it). 422 MB that nobody reads is a fact about our
#: decompile, not about buildings, and it is recorded here so it is not
#: rediscovered.
SNAPSHOT_FILES = (
    "L0.jsonl", "curve.index.json", "curtain.index.json",
    "sketch.index.json", "family_placement.index.json", "group.index.json",
    "passport.json", "tree.json", "verify.json", "named.json",
)


#: Names that the pipeline APPENDS TO as the run proceeds. The cold path
#: does not compress them: a compressed file that later has a raw tail
#: appended to it is two truths about one snapshot.
APPEND_TARGETS = ("L0.jsonl",)

#: 🔴 THE CLOSED LIST OF NAMES REQUIRED TO STAND UNDER THE WITNESS (F-343,
#: second half, 30.08.2026).
#:
#: `verify_digests` has been able to accept `expected=` since F-343
#: itself, and NOBODY passed it. Without it the checker goes BY THE
#: MANIFEST'S LINES, and never sees a file that is not in the manifest: a
#: manifest of six lines against ten names returned `{}`, i.e. "everything
#: matched" exactly where less than two thirds had been checked. The
#: instrument was right about ITS OWN LINES and read as an answer about
#: the SNAPSHOT.
#:
#: 🔴 APPENDED FILES ARE EXCLUDED, AND THIS IS NOT A RELAXATION.
#: `L0.jsonl` is in `APPEND_TARGETS`: the cold path does not compress it,
#: so `record_digest` is never called on it, so it has no manifest line
#: BY DESIGN. Measurement on the live corpus (93 directories, 53 with a
#: manifest, 30.08.2026):
#:
#:     expected = all ten names     28 alerts in 19 decompiles
#:                                  16 of them are `L0.jsonl`, and in ALL
#:                                  16 it lies RAW (0 of 16 compressed)
#:     expected = these nine        12 alerts in 3 decompiles, all real:
#:                                  named/passport/tree/verify without a
#:                                  witness
#:
#: Sixteen out of sixteen is not a distribution but a construction: a
#: guard with the full list would be red forever, for a reason there is
#: nothing to fix. Exactly what the denominator is asking: "what will
#: this guard show on the day when there is nothing left to fix".
WITNESSED_SNAPSHOT_FILES = tuple(
    name for name in SNAPSHOT_FILES if name not in APPEND_TARGETS)


def _newest_mtime(directory: Path) -> float:
    """The most recent edit of ANY file in the directory, 0.0 if there are
    no files.

    Not `last_access` and not `status.json.updated_at`: both speak to
    what was done WITH the snapshot, while the question here is different
    — whether the PIPELINE is writing to it right now. Only the mtime of
    the files themselves answers that.
    """
    newest = 0.0
    try:
        for path in directory.rglob("*"):
            try:
                if path.is_file():
                    newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        return 0.0
    return newest


def silent_days(directory: Path, now: float) -> float:
    """How many days no file in the directory has changed."""
    newest = _newest_mtime(directory)
    if newest <= 0.0:
        return 0.0
    return max(0.0, (now - newest) / 86400.0)


def _has_raw_cold_files(directory: Path) -> bool:
    """Whether there is anything to compress via the cold path (other
    than files being appended to).

    The list is taken from `WITNESSED_SNAPSHOT_FILES` and not rebuilt
    here from scratch: two expressions of "everything except what's
    appended to" would be a named defect of this tree, and it is guarded
    by `agreements.близнец_компилятора_несёт_
    диспозицию`.
    """
    return any((directory / name).is_file()
               for name in WITNESSED_SNAPSHOT_FILES)


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_last_transition(path: Path) -> Optional[dict[str, Any]]:
    """The last A5Phase transition record in a run journal, or None.

    A5 journals interleave TWO event shapes (kukai/ir/a5_recovery.py):
    ``"transition"`` (carries ``phase``, one per A5Phase change — Prepared
    -> ... -> Completed) and effect-level bookkeeping (``"effect_started"``
    /``"effect_finished"``, one per created/deleted element, hundreds per
    run and NO ``phase`` field). Live measurement 2026-07-29
    (sob62_fas_r23_v10, run stalled at "Rebuilt"): the journal's last LINE
    is an effect_finished, not a transition — reading the bare last line
    would misreport an in-progress run's own recorded phase as unknown
    rather than as the (also correctly blocking) truth. Reads the whole
    file — journals are one line per event, not per model element in the
    transition case, and even the effect-heavy tail is a few hundred
    short lines — no streaming needed."""
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("event") == "transition":
            return row
    return None


@dataclasses.dataclass(frozen=True)
class LiveCheck:
    live: bool
    reason: str = ""


def check_live(directory: Path) -> LiveCheck:
    """Any of the iron-clad conditions -> live, never touched by any rule.

    Fails CLOSED: a missing or unparsable control file counts as live —
    an ambiguous "is this run done" answer is not a license to guess.

    🔴 THE CAUSE NAMES WHAT IS THERE, NOT A DISJUNCTION (audit of
    29.08.2026, E-33). The line "X missing or Y != Z" is logically true
    and FALSE for the reader. Measurement on the live corpus: of 46
    blocked snapshots, 32 carried a message about a cause that does NOT
    hold. All 24 snapshots with the text "status.json missing or stage !=
    done" DO HAVE the file, and the real cause is `stage`, which for them
    is `error` (19), `geometry` (2), `cancelled` (2), `passport` (1). Of
    the 14 with text about `L0.checkpoint.json`, 6 lack the file, while 8
    have it and it carries `footer_written: False`.

    What was hidden was not only the fact but the KIND: nineteen
    snapshots are decompiles that FAILED WITH AN ERROR, and the operator
    read "file is missing" about them. The next move differs across the
    three kinds: "file is missing" calls for fixing the layout, `stage:
    error` calls for looking at WHY the decompile failed, `cancelled`
    calls for nothing. This line is the only thing the cleaner hands a
    person about a snapshot it does NOT TOUCH, and an error in it sends
    the person the wrong way.

    The instrument's answer (`live`) DOES NOT CHANGE on any input — only
    whether a next move can be made from it changes. The value is
    printed (`stage=%r`), not just the field's name: a kind of finding
    that is not named stays as silent as its absence.
    """
    checkpoint = _read_json(directory / "L0.checkpoint.json")
    if checkpoint is None:
        return LiveCheck(True, "L0.checkpoint.json отсутствует или нечитаем "
                               "— прогон считаем незавершённым (fail-closed)")
    if checkpoint.get("footer_written") is not True:
        return LiveCheck(True, "L0.checkpoint.json есть, но footer_written="
                               "%r, не true — поток L0 не закрыт"
                               % (checkpoint.get("footer_written"),))

    status = _read_json(directory / "status.json")
    if status is None:
        return LiveCheck(True, "status.json отсутствует или нечитаем — "
                               "стадия неизвестна (fail-closed)")
    stage = status.get("stage")
    if stage != "done":
        return LiveCheck(True, "status.json есть, stage=%r, не 'done' — "
                               "разбор не завершён" % (stage,))

    a5_dir = directory / "a5_runs"
    if a5_dir.is_dir():
        for journal in sorted(a5_dir.glob("*.state.jsonl")):
            record = _read_last_transition(journal)
            phase = (record or {}).get("phase")
            if phase != "Completed":
                return LiveCheck(
                    True, f"a5_runs/{journal.name} last transition phase "
                          f"is {phase!r}, not 'Completed'")

    return LiveCheck(False)


def snapshot_updated_at(directory: Path) -> Optional[float]:
    """status.json's own updated_at (I4: the only wall-clock this corpus
    trusts) — falls back to nothing (None) rather than a directory mtime
    a copy/restore/backup can reset silently.

    🔴 `bool` IS A SUBCLASS OF `int`, AND THIS IS NOT NITPICKING (audit
    29.08.2026, F-215). `isinstance(True, (int, float))` is true,
    `float(True)` == 1.0, meaning a corrupted `updated_at: true` produced
    not "time unknown" but January 1, 1970 — an age of 20,695 days, and
    `plan_actions` scheduled `delete_inactive`, i.e. `rmtree` on the
    directory (verified by execution, in three forms: `true`, `0`, `1`).
    This function was fail-closed exactly for a STRING and `null`, but
    for three number-like values it was fail-open, and it opened toward
    DELETING THE ONLY COPY: the most expensive mistake this instrument
    can make, by its own law ("a compression error costs CPU time, a
    deletion error costs the only copy").

    The TYPE check and the VALUE check are both mandatory here, and
    neither REPLACES the other: without `isinstance(..., bool)`, `True`
    would leak through as any large number; without the lower bound,
    `updated_at: 0` would give the same year of 1970. The order of the
    lines is also mandatory — `bool` is asked FIRST.

    `None` here is CORRECT and already distinguished: `_touchable` prints
    "age unknown, treated as too young", meaning the silence has a cause
    that can be questioned. Dropping the cleaner's entire run because of
    one corrupted file would be more expensive.
    """
    status = _read_json(directory / "status.json")
    value = (status or {}).get("updated_at")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    stamp = float(value)
    if stamp < MIN_PLAUSIBLE_UPDATED_AT:
        return None
    return stamp


def last_access_ts(directory: Path, now: float) -> float:
    """Most recent read — THE MAXIMUM OF TWO MARK CARRIERS, not just one.

    1. OLD: ``.last_access`` INSIDE the directory. Until 07.09.2026 every
       read wrote it; writing stopped, but 75 decompiles on disk still
       carry it, and it is their only protection from gzip. It must be
       read.
    2. NEW: ``.last_access`` in the EXTERNAL JOURNAL
       (``snapshot_io.access_journal_dir``) — today's read places the
       mark there, because reading does not change the decompile
       directory itself.

    THE MAXIMUM, not "whichever comes first": for a decompile read both
    before and after the move, the freshest mark can sit on either of the
    two, and preferring one carrier over the other would hand over to
    gzip a decompile that is being read right now.

    A snapshot no reader has EVER opened since it was written (neither
    marker) is exactly as idle as its own completion time — counting it
    as "just accessed" would give an unread snapshot infinite protection,
    the opposite of what the marker is for.
    """
    stamps: list[float] = []
    for marker in (directory / LAST_ACCESS_MARKER,
                   access_journal_dir(directory) / LAST_ACCESS_MARKER):
        try:
            stamps.append(marker.stat().st_mtime)
        except OSError:
            continue
    if stamps:
        return max(stamps)
    updated = snapshot_updated_at(directory)
    return updated if updated is not None else now


def document_fingerprint_key(directory: Path) -> tuple[str, ...]:
    """Group key for retention — document_fingerprint, NEVER the directory
    name (v1..v13-style names carry no ordering guarantee, and a
    hand-renamed directory must not silently leave its group)."""
    profile = _read_json(directory / "open_model.profile.json")
    fp = (profile or {}).get("document_fingerprint")
    if isinstance(fp, dict):
        for field_name in ("project_uid", "path_name", "title"):
            value = fp.get(field_name)
            if isinstance(value, str) and value:
                return ("fingerprint", field_name, value)
    # No usable identity: never group with anything else, so an unrelated
    # snapshot's retention count can't accidentally sweep this one up.
    return ("no_fingerprint", directory.name)


def discover_snapshots(root: Path) -> list[Path]:
    """Immediate subdirectories that look like a real pipeline output —
    status.json is written by every run this janitor should ever see
    (§18.1/§18.2 status discipline), a directory without one is not ours
    to manage."""
    if not root.is_dir():
        return []
    return sorted(
        child for child in root.iterdir()
        if child.is_dir() and (child / "status.json").is_file())


def discover_refusal(root: Path) -> Optional[str]:
    """``None``, if the corpus root is in place; otherwise the REASON in
    words.

    🔴 THE ANSWER OF `discover_snapshots` DOES NOT CHANGE — the cleaner
    must not be dropped because of a missing root — but the SILENCE gets
    a REASON that can be questioned. The law is written in this tree
    word for word (`install_paths`,
    `viewer/scene.corpus_unreachable_reason`): any zero taken from the
    corpus must travel with proof that the corpus was reachable.

    The price is higher here specifically than for the tree's other
    zeros: an empty list makes the cleanup plan empty, and "there is no
    corpus" is printed with the same words as "the corpus is clean,
    nothing to clean". The first requires naming the root, the second
    requires nothing — and the next move differs between them.

    The three outcomes are distinguished on purpose: doesn't exist at
    all, is not a directory, is a directory without a single snapshot.
    Merging them into one would mean repeating the very defect this
    function is written against.
    """
    if not root.exists():
        return (f"корня корпуса нет: {root} — это факт о МАШИНЕ, а не о "
                f"слепках. СЛЕДУЮЩИЙ ХОД: задай корень аргументом --root "
                f"каталогом, где лежат разборы")
    if not root.is_dir():
        return (f"корень корпуса не каталог: {root} — уборщику нечего "
                f"обходить. СЛЕДУЮЩИЙ ХОД: проверь путь")
    if not any(child.is_dir() and (child / "status.json").is_file()
               for child in root.iterdir()):
        return (f"каталог {root} есть, но ни одного слепка со status.json в "
                f"нём нет: обойти было ЧТО, находить — нечего. Это НЕ то же "
                f"самое, что отсутствующий корень")
    return None


@dataclasses.dataclass(frozen=True)
class SnapshotState:
    directory: Path
    live: LiveCheck
    age_hours: Optional[float]
    idle_hours: Optional[float]
    fingerprint: tuple[str, ...]
    recency: float          # higher = more recent; for revision ranking
    #: Days without a single edit to any file in the directory. Measured
    #: here, not in `plan_actions`: that one is declared a PURE function
    #: over already-captured states, and I/O inside it would strip tests
    #: of the ability to feed in synthetic data. Every new question to the
    #: disk lives in `classify`.
    silent_days: float = 0.0
    #: Whether there are raw files that the cold path has the right to
    #: compress.
    has_raw_cold_files: bool = False
    #: 🔴 WHETHER SOURCE CODE REFERENCES THIS SNAPSHOT, and if so, from
    #: where.
    #:
    #: The 21.08 dry run: 38 directories up for deletion, and 16 of them
    #: are named in code — among them `sob62_fas_r23_v19`, which the PROD
    #: viewer visits, and `sob62_fas_r23_v11`/`v13`, which the clash and
    #: curtain tests read. The very first honest `--apply` would have
    #: painted the tests red and cut the legs out from under the viewer.
    #: The retention policy simply had no concept of "the snapshot is
    #: referenced" — that concept lives in
    #: `kukai/ir/decompile/snapshot_pins.py`.
    pinned: Optional[str] = None


def classify(directory: Path, now: float,
             pins: Optional[dict] = None) -> SnapshotState:
    """Capture the state of a snapshot. ``pins`` is computed ONCE per run
    (walking the whole source tree costs seconds), so it arrives from the
    outside rather than being built here for every directory."""
    updated = snapshot_updated_at(directory)
    age_hours = (now - updated) / 3600.0 if updated is not None else None
    accessed = last_access_ts(directory, now)
    idle_hours = max(0.0, (now - accessed) / 3600.0)
    return SnapshotState(
        directory=directory,
        live=check_live(directory),
        age_hours=age_hours,
        idle_hours=idle_hours,
        fingerprint=document_fingerprint_key(directory),
        recency=updated if updated is not None else accessed,
        silent_days=silent_days(directory, now),
        has_raw_cold_files=_has_raw_cold_files(directory),
        pinned=pin_reason((pins or {}).get(directory.name)),
    )


@dataclasses.dataclass(frozen=True)
class PlannedAction:
    directory: Path
    action: str    # "delete_old_revision" | "delete_inactive" | "gzip" | "skip"
    reason: str


def _touchable(state: SnapshotState) -> Optional[str]:
    """None if the iron-clad checks allow ANY action at all; else the
    reason it must stay untouched."""
    if state.live.live:
        return state.live.reason
    if state.age_hours is None:
        return "status.json has no usable updated_at — age unknown, treated as too young"
    if state.age_hours < MIN_AGE_HOURS:
        return f"age {state.age_hours:.2f}h < MIN_AGE_HOURS={MIN_AGE_HOURS}h"
    return None


def _is_gzipped(directory: Path) -> bool:
    """True once every present-at-capture-time snapshot file is already
    gzipped — used to skip a redundant gzip action, not to judge whether
    the stage ran at all (an absent side index is neither)."""
    any_raw = any((directory / name).is_file() for name in SNAPSHOT_FILES)
    return not any_raw


def plan_actions(
    states: Iterable[SnapshotState],
) -> list[PlannedAction]:
    """Pure function over already-classified snapshots — no I/O, so the
    test suite can hand it synthetic states and check the decision alone."""
    states = list(states)
    actions: dict[Path, PlannedAction] = {}

    # Rule 1: retention, per document_fingerprint group.
    groups: dict[tuple[str, ...], list[SnapshotState]] = {}
    for state in states:
        groups.setdefault(state.fingerprint, []).append(state)
    for key, members in groups.items():
        if key[0] == "no_fingerprint" or len(members) <= KEEP_REVISIONS:
            continue
        ordered = sorted(members, key=lambda s: s.recency, reverse=True)
        for stale in ordered[KEEP_REVISIONS:]:
            # A pin outranks the retention policy and is checked FIRST:
            # "there are too many of these revisions" does not cancel the
            # fact that working code references one of them.
            if stale.pinned:
                actions[stale.directory] = PlannedAction(
                    stale.directory, "skip",
                    f"would delete_old_revision but {stale.pinned}")
                continue
            blocked = _touchable(stale)
            if blocked is not None:
                actions[stale.directory] = PlannedAction(
                    stale.directory, "skip",
                    f"would delete_old_revision but {blocked}")
                continue
            actions[stale.directory] = PlannedAction(
                stale.directory, "delete_old_revision",
                f"{len(members)} revisions of {stale.fingerprint}, "
                f"keeping the {KEEP_REVISIONS} most recent")

    # Rules 2/3: per-snapshot idle checks — skip anything retention
    # already decided (delete beats gzip; a skip from rule 1 still gets a
    # fresh chance under rules 2/3).
    for state in states:
        if state.directory in actions and actions[state.directory].action != "skip":
            continue
        blocked = _touchable(state)
        if blocked is not None:
            quiet = state.silent_days
            if (quiet >= SILENT_DAYS_FOR_GZIP
                    and state.has_raw_cold_files):
                actions[state.directory] = PlannedAction(
                    state.directory, "gzip_cold",
                    f"{blocked}, НО ни один файл не менялся {quiet:.1f}д "
                    f">= SILENT_DAYS_FOR_GZIP={SILENT_DAYS_FOR_GZIP}д: "
                    f"сжимаем всё, кроме дописываемых {APPEND_TARGETS}")
                continue
            actions.setdefault(state.directory, PlannedAction(
                state.directory, "skip", blocked))
            continue
        if state.idle_hours >= INACTIVE_DELETE_DAYS * 24.0:
            if state.pinned:
                actions[state.directory] = PlannedAction(
                    state.directory, "skip",
                    f"would delete_inactive but {state.pinned}")
                continue
            actions[state.directory] = PlannedAction(
                state.directory, "delete_inactive",
                f"idle {state.idle_hours / 24.0:.1f}d >= "
                f"INACTIVE_DELETE_DAYS={INACTIVE_DELETE_DAYS}d")
            continue
        if state.idle_hours >= IDLE_HOURS and not _is_gzipped(state.directory):
            actions[state.directory] = PlannedAction(
                state.directory, "gzip",
                f"idle {state.idle_hours:.1f}h >= IDLE_HOURS={IDLE_HOURS}h")
            continue
        actions.setdefault(state.directory, PlannedAction(
            state.directory, "skip", "no rule applies"))

    return [actions[state.directory] for state in states]


def _gzip_file_verified(raw: Path) -> None:
    """Compress raw -> raw.gz, verify the gzip readback is byte-identical
    to the original BEFORE removing it — a corrupt compress must never
    cost the only copy."""
    gz = gz_path(raw)
    tmp = gz.with_suffix(gz.suffix + ".tmp")
    original = raw.read_bytes()
    with gzip.open(tmp, "wb") as dst:
        dst.write(original)
    with gzip.open(tmp, "rb") as check:
        if check.read() != original:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"gzip readback mismatch for {raw} — raw file kept")
    os.replace(tmp, gz)
    # 🔴 THE WITNESS OF WHAT THE FILE WAS IS RECORDED BEFORE `unlink()` —
    # AFTERWARD THERE IS NOWHERE TO GET IT FROM. The check above is sound
    # and verifies the COMPRESSOR: it lives for exactly one instant
    # between the write and the deletion. The 20.08.2026 FAIL control
    # named the boundary by name:
    #     container corrupted    -> BadGzipFile, LOUDLY
    #     content swapped        -> the instrument's answer DID NOT
    #                                CHANGE AT ALL
    # After `unlink()` the only copy is left without a witness of what it
    # was, and checking the digest is useless BY CONSTRUCTION: a swap
    # that is not part of the digest will never move it. The bytes have
    # already been read above — a second read is not needed, the cost is
    # zero.
    record_digest(raw.parent, raw.name, original)
    raw.unlink()


def execute(action: PlannedAction) -> None:
    if action.action == "gzip":
        for name in SNAPSHOT_FILES:
            raw = action.directory / name
            if raw.is_file():
                _gzip_file_verified(raw)
    elif action.action == "gzip_cold":
        # Cold path: the snapshot is listed as live, but has been silent
        # for weeks. We do not touch names being appended to — see
        # APPEND_TARGETS.
        for name in SNAPSHOT_FILES:
            if name in APPEND_TARGETS:
                continue
            raw = action.directory / name
            if raw.is_file():
                _gzip_file_verified(raw)
    elif action.action in ("delete_old_revision", "delete_inactive"):
        shutil.rmtree(action.directory)
    elif action.action == "skip":
        pass
    else:  # pragma: no cover - defensive, plan_actions is a closed set
        raise ValueError(f"unknown action {action.action!r}")


def _verify_all(root: Path) -> int:
    """Verify EVERY compressed snapshot against what it was at the moment
    of compression.

    🔴 THREE OUTCOMES, NOT TWO, AND THE THIRD IS THE MAIN ONE.
    `verify_digests` returns an EMPTY dict for "everything matched", a
    dict of `name -> reason` for mismatches, and a SEPARATE shape
    `{"": ...}` for "there is no manifest". The last is neither a
    mismatch nor silence: there is NOTHING to check against, and
    declaring such a decompile as matching would mean printing green
    where nothing was counted.

    The first version of this function caught the third outcome as `rows
    is None` and printed decompiles WITHOUT a manifest as mismatches with
    an empty name. The contract was not read — exactly the mistake this
    whole block is written against.

    🔴 THE RETURN CODE ANSWERS FOR BOTH WAYS OF FAILING TO VERIFY (audit
    29.08.2026, F-214). Before the fix it read ONLY `mismatched`, meaning
    the gate was green both when there was no root at all
    (`discover_snapshots` returns `[]`, the loop never runs) and when
    there was nothing to check for any decompile. All three numbers were
    already printed; the decision was made on just one of them. The
    instrument answered truthfully the question "were mismatches found
    among what was CHECKED" and read as an answer to "are the compressed
    snapshots intact".

    Three outcomes — three codes, and they cannot be merged: `1` means
    "verification took place and found corruption" (dig into the bytes),
    `2` means verification DID NOT TAKE PLACE (name the root, or compress
    via the cleaner so a manifest appears). The next move differs
    between them, and CI branches on the code.
    """
    # 🔴 THE CAUSE COMES FIRST AND LOUDLY, BEFORE THE NUMBERS — the same
    # convention as in `relift_offline.main` and
    # `bounds_audit.print_measurement`: the reader is stopped by the
    # HEADER, not by a footnote under the table.
    refusal = discover_refusal(root)
    if refusal is not None:
        print("🔴 СВЕРКА НЕ СОСТОЯЛАСЬ: %s" % refusal)
        return 2
    checked = mismatched = unwitnessed = 0
    nameless = 0
    bad: list[str] = []
    thin: list[str] = []
    for directory in discover_snapshots(root):
        rows = verify_digests(directory, expected=WITNESSED_SNAPSHOT_FILES)
        if "" in rows:
            unwitnessed += 1
            continue
        checked += 1
        if not rows:
            continue
        # 🔴 TWO KINDS IN ONE DICT, AND THEY ARE SEPARATED BY STRUCTURE,
        # NOT BY TEXT. `verify_digests` puts into `bad` both "content
        # diverged" (the manifest line exists, the bytes differ) and
        # "there is no manifest line at all". The actions for them
        # differ: the first is to dig into the bytes, the second is to
        # compress via the cleaner so the line appears. Parsing a
        # substring of the reason would mean matching the LABEL instead
        # of the subject.
        #
        # A separator with no second knowledge carrier: the same check
        # WITHOUT the closed list sees only manifest lines, so its answer
        # is exactly the first kind, and the difference between the two
        # answers is exactly the second.
        #
        # THE PRICE IS STATED: the second pass runs ONLY over decompiles
        # that have already failed at something (on the live corpus of
        # 30.08.2026 — 3 of 53), so it does not double the check. A full
        # second pass would have cost another 10.7 s.
        plain = verify_digests(directory)
        missing = sorted(name for name in rows if name not in plain)
        if missing:
            nameless += len(missing)
            thin.append("%s: под свидетелем нет %d имён — %s" % (
                directory.name, len(missing), ", ".join(missing)))
        if len(missing) < len(rows):
            mismatched += 1
            bad.append("%s: %s" % (
                directory.name,
                "; ".join("%s — %s" % kv for kv in sorted(plain.items()))))
    print("сверено разборов: %d" % checked)
    print("расхождений:      %d" % mismatched)
    print("БЕЗ СВИДЕТЕЛЯ:    %d  (сжаты до появления манифеста — сверять НЕЧЕМ, "
          "это НЕ «сошлось»)" % unwitnessed)
    # 🔴 THE FOURTH NUMBER THAT DID NOT EXIST (F-343). A manifest of six
    # lines against nine names answers "matched" — the truth about ITS
    # OWN LINES, read as an answer about the SNAPSHOT. The number states
    # how many names the checker stayed silent about while HAVING the
    # file on disk.
    print("ИМЁН БЕЗ СТРОКИ:  %d  (файл есть, строки в манифесте нет — "
          "манифест ПОЛОН НЕ БЫЛ)" % nameless)
    for line in bad[:20]:
        print("  🔴 " + line)
    for line in thin[:20]:
        print("  🔴 " + line)
    if mismatched:
        return 1
    if nameless:
        # Code 2, not 1, and this is not a small thing: the codes have a
        # DIFFERENT next move. `1` means "verification took place and
        # found corruption" — dig into the bytes. Here the bytes are
        # beside the point: for these names verification DID NOT TAKE
        # PLACE, and the fix is the cleaner writing the line in. Exactly
        # the work that code 2 names.
        print("🔴 СВЕРКА НЕПОЛНА: %d имён лежат на диске без строки в "
              "манифесте. «Расхождений 0» здесь — факт о СВЕРЕННОМ "
              "подмножестве, а не о слепках" % nameless)
        return 2
    if checked == 0:
        # There was NOTHING to check. "Zero mismatches among zero
        # checked" is a statement about an EMPTY set, and passing it off
        # as "intact" means printing green where nothing was counted.
        #
        # There is deliberately NO threshold on the SHARE without a
        # witness here: today it is 38 of 91 (42%), and any threshold
        # number would be assigned without an incident behind it. The
        # share is reported as output; a threshold gets introduced once
        # someone decides to hold it.
        print("🔴 СВЕРЕНО НОЛЬ РАЗБОРОВ из %d обнаруженных: манифеста нет ни "
              "у одного. «Расхождений 0» здесь — факт о ПУСТОМ множестве, а "
              "не о целости слепков" % unwitnessed)
        return 2
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root", type=Path, default=Path("backend/data/decompile"),
        help="directory holding one subdirectory per snapshot")
    parser.add_argument(
        "--apply", action="store_true",
        help="execute the plan (default: print it and change nothing)")
    parser.add_argument(
        "--gzip-only", action="store_true",
        help="ТОЛЬКО сжатие; удаление невозможно по построению (решение "
             "владельца 20.08.2026)")
    parser.add_argument(
        "--verify", action="store_true",
        help="сверить сжатые слепки с записанными дайджестами и выйти; "
             "ничего не планирует и ничего не трогает")
    args = parser.parse_args(argv)

    if args.verify:
        return _verify_all(args.root)

    now = time.time()
    snapshots = discover_snapshots(args.root)
    # Pins are computed ONCE by walking the source tree: asking for them
    # on every snapshot would mean parsing the tree 88 times.
    #
    # 🔴 THE ROOT IS TAKEN FROM THE PACKAGE, NOT BY STEPPING UPWARD
    # (29.08.2026). This used to say `Path(__file__).resolve().parents[1]`,
    # i.e. THE PACKAGE ITSELF `kir/`, and the walk searched inside it for
    # `kir/kukai` and `kir/tools` — directories that do not exist. Live,
    # this always gave `pins == {}`, and neither of the two guards below
    # (the lines "would delete_old_revision but …" / "would
    # delete_inactive but …") could ever fire. Counting steps upward is
    # correct for exactly one layout; the package itself knows where the
    # package is.
    import kir as _kir_pkg
    _tree_root = Path(_kir_pkg.__file__).resolve().parent.parent
    pins = pinned_snapshots([d.name for d in snapshots], _tree_root)
    states = [classify(d, now, pins) for d in snapshots]
    actions = plan_actions(states)

    # 🔴 A BLIND WALK HAS NO RIGHT TO PERMIT DELETION (29.08.2026). "No
    # pins were found" and "there was nothing to search" are one phrase
    # and different facts, and their price differs: a pinning error costs
    # disk space, an error the other way costs deleted evidence that
    # cannot be recovered. So this is not a warning but a CUTOFF: a plan
    # that contains no deletion cannot be executed incorrectly.
    _reach = scan_reach(_tree_root)
    _blind = _reach.reason()
    if _blind is not None:
        actions = [
            a if not a.action.startswith("delete")
            else PlannedAction(a.directory, "skip",
                               f"would {a.action} but {_blind}")
            for a in actions
        ]
        print(f"🔴 ЗАКРЕПЛЕНИЯ НЕ СЧИТАНЫ: {_blind}")
        print("   удаления сняты с плана целиком; сжатие не затронуто")
    else:
        print(f"      закрепления: прочитано {_reach.files} файлов в "
              f"{', '.join(_reach.roots_read)}; закреплено {len(pins)} "
              f"из {len(snapshots)}")

    # 🔴 OWNER'S DECISION OF 20.08.2026: COMPRESSION ONLY, DO NOT TOUCH
    # DELETION. Bought by a number: a dry run over 85 decompiles gives
    # `delete_old_revision` for 37 decompiles and 2.30 GB against 0.15 GB
    # of compression — DELETION frees fifteen times more space. And it
    # deletes exactly the corpus the canon's published numbers stand on
    # (`k2_ar_rd_v6/v7/v8`, `sob62_fas_r23_v12/v18`,
    # `snowdon_plumb_v2/v3`): the canon requires REMEASURING, not quoting
    # — there would be nothing left to remeasure.
    #
    # The cutoff stands HERE, before `execute`, not as a check inside it:
    # a plan that contains NO deletion cannot be executed incorrectly. A
    # guarantee by construction is stronger than one merely verified. The
    # second half is the assertion below: it catches the case where the
    # filter one day gets rewritten past its meaning.
    if args.gzip_only:
        # `gzip_cold` is also compression, and the filter must let it
        # through: it selects by MEANING ("we delete nothing"), not by a
        # single name.
        actions = [a for a in actions
                   if a.action in ("gzip", "gzip_cold", "skip")]
        assert not [a for a in actions if a.action.startswith("delete")], (
            "--gzip-only пропустил удаление: фильтр разошёлся со своим смыслом")

    by_action: dict[str, list[PlannedAction]] = {}
    for action in actions:
        by_action.setdefault(action.action, []).append(action)

    # 🔴 THE CAUSE IS PRINTED BEFORE THE NUMBER, not after: "0
    # slepok(ov)" under a missing root reads as "clean", and the reader
    # goes no further.
    _no_corpus = discover_refusal(args.root)
    if _no_corpus is not None:
        print(f"🔴 СЛЕПКИ НЕ ОБХОДИЛИСЬ: {_no_corpus}")
    print(f"snapshot janitor: {len(snapshots)} snapshot(s) under {args.root}")
    if args.gzip_only:
        print("  --gzip-only: удаление ИСКЛЮЧЕНО из плана "
              "(решение владельца 20.08.2026)")
    print(f"  IDLE_HOURS={IDLE_HOURS} MIN_AGE_HOURS={MIN_AGE_HOURS} "
          f"KEEP_REVISIONS={KEEP_REVISIONS} "
          f"INACTIVE_DELETE_DAYS={INACTIVE_DELETE_DAYS}")
    for kind in ("delete_old_revision", "delete_inactive", "gzip",
                 "gzip_cold", "skip"):
        rows = by_action.get(kind, [])
        print(f"\n  {kind}: {len(rows)}")
        for row in rows:
            print(f"    {row.directory}  — {row.reason}")

    if not args.apply:
        print("\ndry-run (no changes made) — pass --apply to execute")
        return 0

    errors = 0
    for action in actions:
        if action.action == "skip":
            continue
        try:
            execute(action)
            print(f"applied {action.action}: {action.directory}")
        except OSError as exc:
            errors += 1
            print(f"FAILED {action.action} on {action.directory}: {exc}",
                  file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
