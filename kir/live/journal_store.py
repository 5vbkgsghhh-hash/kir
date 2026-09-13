"""THE PROGRAM JOURNAL OUTLIVES THE PROCESS — otherwise the building's source code does not exist.

THE MEASUREMENT THAT BOUGHT THIS FILE (18.08.2026). The honest-comparison
instrument (`tools/axes_duel.py`) was built, run, and **refused for lack of a
subject**: the right-hand side — what KIR builds itself — did not exist
ANYWHERE in the tree.

    kir/live/journal.py     0 disk accesses; OrderedDict in memory,
                              eviction on the 8th session (`KUKAI_KIR_JOURNAL_SESSIONS`)
    marathon journals         op NAMES only
    acceptance evidence       46 files, 0 with `ops`
    refusal corpus            0 of 2360 lines with a program
    kir_witness.jsonl         skeleton: every numeric sheet replaced with "#" BY CONTRACT
    generator materializer    raw C#, not KIR ops

The header of `journal.py` promises: *"the journal is versioned, diffed,
replayed, and used to compute a verdict for the whole building"*. **None of
the three was possible** — the building lived until eviction and vanished
together with the process.

WHY EVENTS, NOT A STATE SNAPSHOT. Precisely for the sake of those three verbs.
A snapshot answers "what is it now" and does not answer "what changed between
turns"; events answer both, and replay becomes READING rather than a separate
machinery. There are two closed kinds of events (`EVENTS`): `program` — a
program was written to the journal, `stage` — its outcome became known. There
is deliberately no third kind: `sections` (the type geometry of the document)
is held in memory as a per-turn cache and is not part of the building —
writing it here would turn the file into a store of ground snapshots.

🔴 THE PRIVACY BOUNDARY IS A DECISION, NOT AN IMPLEMENTATION DETAIL.
`witness_feed._skeleton()` replaces every numeric sheet with `"#"` **BY
CONTRACT**: "coordinates do not leave the model", and its header states
outright that redacting geometry is the point of that file, not a shortcoming
of it. **Here the coordinates STAY**, and here is how the two cases differ:

* the witness is a corpus of OUTCOMES; it travels between installs and serves
  compiler coverage statistics — someone else's geometry is of no use to any
  consumer of it;
* this journal is the SOURCE CODE OF THE BUILDING for that same install, where
  the building is actually being built. A program without coordinates is not a
  program: it cannot be replayed, compared, or drawn from. Redacting them
  would give us a file that looks like a solution to the problem and does not
  solve it.

The consequences follow, and they are mandatory: the file lives in
`data/telemetry/` of THIS install, mode `0600` (like `kir_created_ids.jsonl`),
the path is overridden by `KIR_JOURNAL_STORE_PATH`, and an empty value of that
variable TURNS WRITING OFF — a deployment must be able to say so deliberately,
not through a missing directory. Not one line of this data reaches the
open-source `kir/` package: the module lives in the product's `kir/live/`.

WHY THIS IS NOT A FOURTH COPY OF AN FSYNC WRITER. There were two of them in
the tree, both private and fused to their own line format:
`created_ledger._write_line` (0600, the neighboring error file) and
`transfer_journal.record` (fail-open, returns bool). The primitive has been
factored out here once (`append_line`), and `transfer_journal` switched to
it — copies went from three to two. The third one, in `created_ledger`, stays,
and stays DELIBERATELY: `kir/` is published as a separate package under
Apache-2.0 and has no right to import product code. This is not an oversight,
it is the price of the boundary, and it is named here so the next person does
not "tidy it up" and break the publication.

A WRITE REFUSAL HAS NO RIGHT TO BRING DOWN THE TURN. The journal is filled
AFTER planning and BEFORE the write to Revit, i.e. inside a live turn. Hence
fail-open: a failure returns `False` and goes to the log, not upward as an
exception. The return value is not decoration: without it, "the journal is
off" and "the journal crashed" are indistinguishable to a control.

THE COST, MEASURED 18.08.2026 (`PYTHONPATH=. python -m kir.live.journal_store
--bench`, this machine's `/tmp` directory, programs of 20 ops each):

    100 programs    5.37 ms per program
    1000 programs   6.19 ms per program

🔴 The first draft of this line carried **0.30 ms** — a number written BEFORE
the run. The real one turned out eighteen times larger. I am leaving the
admission here rather than removing it: this file is about the fact that what
is not written does not exist, and a number not taken by an instrument is
exactly such a nonexistent record.

And the second half of the measurement — the one that matters more: **the
addition to the HOT PATH**, `journal.append` with and without the store, same
run:

    100 programs    OFF 0.042 ms · ON 6.415 ms · difference +6.37 ms
    1000 programs   OFF 0.044 ms · ON 6.098 ms · difference +6.05 ms

🔴 TWO CLAIMS IN THIS PARAGRAPH WERE CHECKED ON THE EVENING OF 18.08. ONE WAS
CONFIRMED BY THE RUN, THE OTHER TURNED OUT TO BE THE ANSWER TO A DIFFERENT
QUESTION. Read this note before the numbers above.

**"FLAT WITH VOLUME" — TRUE, AND NOW IT IS A MEASUREMENT, NOT AN ARGUMENT.**
Previously flatness was derived from the mechanism ("you pay for fsync, not
for bytes"), i.e. it was reasoning. Measured `append_line` on a growing file,
same disk (`/dev/vda1`, the only one on the machine), programs of 6 walls
each, median of 60 writes at each depth:

    lines in file        10      100     1000    10000
    median, ms       39.477    4.904    4.713    5.054
    size, KB             51      116      766     7270

From 100 to 10000 lines the cost does not move. The first point is warm-up,
not a slope.

**"0.04% OF THE TURN" — THE ANSWER TO A QUESTION NOT ASKED HERE.** The
denominator is taken from the full turn (~14 s), while the live consumer of
this write is `plan_stream.publish`, which has its own budget, seven thousand
times smaller: **2 ms per program**
(`test_live_plan_stream::test_long_run_memory_and_time`). Against THIS
denominator the cost is not 0.04% but more than a hundred percent.

Measured by substitution on 400 programs, not derived:

    write OFF                          0.430 ms/program    test GREEN
    write ON, file BEING WRITTEN       7.252 ms/program    test RED
                                       the journal adds ~6.8 ms

🔴 AND THE FIRST DRAFT OF THIS NOTE, WRITTEN AN HOUR AGO, CARRIED **2.528**
HERE — AND THAT WAS THE COST OF A REFUSAL, NOT THE COST OF A WRITE. The suite
was run under a user with no rights to the service directory: `append_line`
raised `PermissionError`, `fail-open` swallowed it, and the instrument printed
the cost of a write THAT NEVER HAPPENED. A threefold understatement. Caught by
the fact that the same measurement with a file actually being written gave
7.252. The condition is now set by the test itself, not by the environment.

In other words, **`publish` on its own cost 0.43 ms against a 2 ms budget —
the margin was almost fivefold, and the write spent it fourfold over.** The
budget was written when a durable journal did not yet exist; it is not
"wrong", it is OLDER than the subject.

🔴 **THE CHOICE HERE IS NOT AN ENGINEERING ONE BUT THE OWNER'S, AND SO IT HAS
NOT BEEN MADE.** Both sides are named by number:

* leave it as is — construction pays **~7.3 ms per program** (a floor of four
  programs — 29 ms per turn out of ~14 s, i.e. 0.2%), and EVERY program that
  reaches `append` survives a MACHINE crash;
* batch the fsyncs — construction pays fractions of a millisecond, but on a
  machine crash ALL programs accumulated between flushes are lost; how many
  exactly is precisely the batch size, and it will have to be named by
  number.

Until the choice is made, nothing changes: the write stays durable, and the
test stays red HONESTLY — it shows a real overrun of a real budget, not a
breakage. Silently raising the budget would mean fixing the guard so that it
stops turning red.

The measurement condition is named: on a slow disk the cost will be
different, and it must be measured where the service actually lives. Checked
separately that prod CAN write: the service runs as `kukai`, and the
`data/telemetry` directory is owned by `kukai`. The absence of the
`kir_programs.jsonl` file in prod means "not a single program has gone
through the live plan", not "no permissions" — the first guess was exactly
about permissions and it was wrong: it measured MY permissions, not the
service's.

WHAT THIS MODULE DOES NOT KNOW. It does not interpret programs, does not
compile, and does not draw. It does not decide whether anything got built:
the stage arrives from outside and is stored as a fact. And it does not
repair loss — a program that never reached `append` will not appear here, and
it will not pretend that it will.

    PYTHONPATH=. venv/bin/python tools/programs_audit.py
    PYTHONPATH=. venv/bin/python tools/programs_audit.py --export /tmp/p.json
"""
from __future__ import annotations

import json
import logging
import os
from kir import env  # noqa: E402  (dependency-free submodule — creates no ring)
import pathlib
import time
from typing import Any, Iterable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

SCHEMA = "kir-journal-store/2"
PREVIOUS_SCHEMAS = frozenset({"kir-journal-store/1"})

#: Path override. An empty string means OFF (deliberately, not by oversight).
PATH_ENV = "KIR_JOURNAL_STORE_PATH"

#: Closed list of event kinds. An unfamiliar kind found while reading IS
#: COUNTED and named in the refusal, rather than dropped silently: the file
#: outlives code versions, and "I didn't understand this line" must be
#: distinguishable from "there was no line".
EVENT_PROGRAM = "program"
EVENT_STAGE = "stage"
EVENT_OPERATION = "operation_bound"
EVENTS = (EVENT_PROGRAM, EVENT_OPERATION, EVENT_STAGE)

#: The store replays the same closed automaton as the live journal.  This is
#: not an independent interpretation of the stages: the literals are repeated
#: here only because ``journal`` imports the store lazily, and a reverse
#: import would create a cycle.
_MAIN_STAGES = ("planned", "grounded", "dispatched", "committed", "accepted")
_SIDE_STAGES = (
    "refused_pre_effect", "rolled_back", "running_unknown",
    "committed_partial",
)
_STAGES = frozenset((*_MAIN_STAGES, *_SIDE_STAGES))
_BUILT_STAGES = frozenset(("committed", "accepted"))
_RANK = {name: index for index, name in enumerate(_MAIN_STAGES)}


def _exact_operation_id(value: Any) -> str | None:
    """Exact transport identity, without truncation or string guessing."""
    if not isinstance(value, str):
        return None
    if not value or value != value.strip() or len(value) > 128:
        return None
    return value


def _exact_receipt_digest(value: Any) -> str | None:
    """Exact lowercase SHA-256 of the late receipt."""
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        return None
    return value


def _identity_claim_valid(row: Mapping[str, Any]) -> bool:
    """Do not let an old/corrupted line acquire new authority."""
    schema = row.get("schema")
    event = row.get("event")
    identity_fields = {
        "operation_ids", "operation_id", "late_receipt_digest",
        "receipt_digest", "reconciled",
    }
    if schema in PREVIOUS_SCHEMAS:
        return event != EVENT_OPERATION and not (identity_fields & set(row))
    if schema != SCHEMA:
        return False
    if event == EVENT_PROGRAM:
        raw_ids = row.get("operation_ids", [])
        if not isinstance(raw_ids, list):
            return False
        ids = [_exact_operation_id(value) for value in raw_ids]
        if any(value is None for value in ids) or len(ids) != len(set(ids)):
            return False
        # A program is born planned. The outcome and the late receipt only
        # ever appear as separate events: allowing them in the initial line
        # would let one unverified record declare itself built.
        return (
            row.get("stage") == "planned"
            and row.get("late_receipt_digest", "") == ""
        )
    if event == EVENT_OPERATION:
        return _exact_operation_id(row.get("operation_id")) is not None
    if event == EVENT_STAGE:
        has_reconciliation = bool(identity_fields & set(row))
        if not has_reconciliation:
            return True
        return (
            row.get("reconciled") is True
            and row.get("stage") == "committed"
            and _exact_operation_id(row.get("operation_id")) is not None
            and _exact_receipt_digest(row.get("receipt_digest")) is not None
            and "operation_ids" not in row
            and "late_receipt_digest" not in row
        )
    return False


def store_path() -> Optional[pathlib.Path]:
    """The journal file, or ``None`` — "writing is off".

    ``None`` means either "this install does not own a writable root" or
    "switched off deliberately", and both cases are equally legitimate. What
    it does NOT mean is "write somewhere": a hardcoded absolute literal has
    already once led to writing into someone else's install (see the
    argument by `coverage_feed._DEFAULT`).
    """
    named = env.get(PATH_ENV)
    if named is not None:
        configured = named.strip()
        return pathlib.Path(configured) if configured else None
    from kir.install_paths import install_data_path
    root = install_data_path("telemetry")
    return None if root is None else root / "kir_programs.jsonl"


def append_line(path: pathlib.Path, row: Mapping[str, Any]) -> None:
    """Append and FLUSH: fsync both the file AND the directory. May raise.

    The directory too — without it the line survives a process crash but not
    a machine crash, and the journal exists precisely for the cases where
    something was cut short.

    Mode `0600` is set on creation: the file carries the coordinates of
    someone else's project (see the privacy boundary in the module header).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    blob = line.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        _write_all(fd, blob)
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def _write_all(fd: int, blob: bytes) -> None:
    """Write out the WHOLE chunk. A short write is a legitimate outcome of `write(2)`.

    🔴 WHAT THIS CLOSES (RT-25). There used to be a single `os.write(fd,
    ...)`, and THE RETURNED BYTE COUNT WAS NOT CHECKED AGAINST ANYTHING.
    `write(2)` is entitled to take less than it was given (a signal midway,
    `RLIMIT_FSIZE`, ran out of space), and that is NOT an error — an error
    would be `-1`. Measured by substituting an `os.write` that takes half, on
    a 98-byte line:

        exception    none           (the store reported "line written")
        on disk      49 bytes       cut off mid utf-8 string
        to a reader  a broken line, yet `_write` returned True

    The cost is precisely in the pair "truncated AND successful": the journal
    exists so that the building has a history, and a history with a truncated
    line looks to the store exactly like an honest one. The same argument by
    which `fsync` is paid here for the directory, not just the file.

    APPEND, DO NOT REFUSE: the remainder is placed with the same descriptor
    using `O_APPEND`, i.e. at the same end of the file, and the line comes
    out whole. Refusing instead of appending would leave a fragment ON DISK
    and merely name it — a whole line is more honest than a named fragment.

    `0` raises: the descriptor no longer accepts bytes, and spinning an empty
    loop would mean hanging the turn instead of naming the refusal. This
    travels upward through `_write`, which logs it and returns False.
    """
    sent = 0
    while sent < len(blob):
        step = os.write(fd, blob[sent:])
        if step <= 0:
            raise OSError(
                f"журнал: записано {sent} байт из {len(blob)}, а очередная "
                f"запись взяла {step} — дописать строку нечем")
        sent += step


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00"


def _write(row: Mapping[str, Any]) -> bool:
    """One line to disk. NEVER raises; True means it landed."""
    path = store_path()
    if path is None:
        return False
    try:
        append_line(path, row)
        return True
    except Exception:  # noqa: BLE001 — fail-open: the turn is worth more than the line
        logger.warning("journal_store: строку не записать (%s)", path,
                       exc_info=True)
        return False


def record_program(key: Sequence[str], record: Any) -> bool:
    """A program was written to the session journal — record it WHOLE.

    `record` is a `journal.ProgramRecord` or anything with the same fields;
    duck typing here is deliberate, so the store does not depend on the
    journal (the dependency runs one way: the journal knows about the store,
    the store does not know about the journal).
    """
    ops = getattr(record, "ops", None)
    if not ops:
        return False
    seq = getattr(record, "seq", 0)
    stage = getattr(record, "stage", "")
    raw_operation_ids = getattr(record, "operation_ids", ()) or ()
    late_receipt_digest = getattr(record, "late_receipt_digest", "") or ""
    if (isinstance(seq, bool) or not isinstance(seq, int) or seq < 0
            or stage != "planned"
            or not isinstance(raw_operation_ids, (tuple, list))
            or any(_exact_operation_id(value) is None
                   for value in raw_operation_ids)
            or len(raw_operation_ids) != len(set(raw_operation_ids))
            or late_receipt_digest != ""):
        return False
    row = {
        "schema": SCHEMA,
        "event": EVENT_PROGRAM,
        "ts": _now(),
        "device_id": str(key[0]) if len(key) > 0 else "",
        "doc_key": str(key[1]) if len(key) > 1 else "",
        "seq": seq,
        "stage": stage,
        "plan_digest": str(getattr(record, "plan_digest", "") or ""),
        "author_digest": str(getattr(record, "author_digest", "") or ""),
        "intent": str(getattr(record, "intent", "") or ""),
        "source": str(getattr(record, "source", "") or ""),
        "operation_ids": list(raw_operation_ids),
        "late_receipt_digest": "",
        "ops": [dict(op) for op in ops if isinstance(op, Mapping)],
    }
    return _write(row)


def record_operation(
    key: Sequence[str],
    seq: int,
    operation_id: str,
) -> bool:
    """Bind one exact transport operation with a separate event."""

    exact = _exact_operation_id(operation_id)
    if (isinstance(seq, bool) or not isinstance(seq, int) or seq < 0
            or exact is None):
        return False
    return _write({
        "schema": SCHEMA,
        "event": EVENT_OPERATION,
        "ts": _now(),
        "device_id": str(key[0]) if len(key) > 0 else "",
        "doc_key": str(key[1]) if len(key) > 1 else "",
        "seq": seq,
        "operation_id": exact,
    })


def record_stage(
    key: Sequence[str],
    seq: int,
    stage: str,
    *,
    operation_id: str = "",
    receipt_digest: str = "",
    reconciled: bool = False,
) -> bool:
    """A program's outcome became known. Written as an EVENT, not a line edit.

    An in-place edit would require rewriting the file and would take away
    from it exactly what it was set up for: history. The last event wins on
    replay.
    """
    if (isinstance(seq, bool) or not isinstance(seq, int) or seq < 0
            or not isinstance(stage, str) or stage not in _STAGES):
        return False
    exact_operation_id = _exact_operation_id(operation_id)
    exact_receipt_digest = _exact_receipt_digest(receipt_digest)
    if reconciled:
        if (stage != "committed" or exact_operation_id is None
                or exact_receipt_digest is None):
            return False
    elif operation_id or receipt_digest:
        # Identity fields without ``reconciled`` have no defined semantics and
        # must not land on disk first and be considered broken afterward.
        return False
    row: dict[str, Any] = {
        "schema": SCHEMA,
        "event": EVENT_STAGE,
        "ts": _now(),
        "device_id": str(key[0]) if len(key) > 0 else "",
        "doc_key": str(key[1]) if len(key) > 1 else "",
        "seq": seq,
        "stage": stage,
    }
    if reconciled:
        row["operation_id"] = exact_operation_id
        row["receipt_digest"] = exact_receipt_digest
        row["reconciled"] = True
    return _write(row)


def read_events(path: pathlib.Path | None = None, *, since: str = ""
                ) -> tuple[tuple[dict[str, Any], ...], str]:
    """Read the journal back: **(events, REFUSAL)** — law §18.2.

    🔴 A PAIR, NOT A LIST, AND THIS WAS BOUGHT IN THIS SAME TREE.
    `created_ledger` in its first draft returned only the rows: the file sits
    with mode 600, the reader got `Permission denied` and returned an empty
    tuple — "couldn't look" and "nothing there" became indistinguishable TO
    THE CALLER. An empty refusal is the only way to say "looked, it's empty".

    A broken line is SKIPPED AND COUNTED: swallowed silently, it would have
    hidden a whole neighboring one (same lesson, same file).
    """
    target = path if path is not None else store_path()
    # 🔴 A PATH AS A STRING IS A LEGITIMATE INPUT, AND IT USED TO FAIL
    # (30.08.2026, found while fixing F-159/F-181). `journal.restore(key,
    # path="/…")` passed a `str` here, `target.exists()` raised
    # `AttributeError`, and `store_unreadable` went outward — i.e. the
    # refusal BLAMED THE STORE for the reader having passed a different type.
    # Measurement: the same file with a `Path` came up fine (2 records), with
    # a `str` it was "cannot read the journal". The coercion belongs here,
    # not at the caller: this IS the public reader's entry point, and a
    # second type check at every caller would be a second carrier of one
    # rule.
    if isinstance(target, (str, os.PathLike)):
        target = pathlib.Path(target)
    if target is None:
        return (), "журнал выключен: путь не задан этой установкой"
    if not target.exists():
        return (), f"файла журнала нет: {target}"
    rows: list[dict[str, Any]] = []
    broken = 0
    unknown = 0
    unsupported_schema = 0
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return (), f"журнал {target} не прочитать: {type(exc).__name__}: {exc}"
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001 — someone else's line, not our defect
            broken += 1
            continue
        if not isinstance(row, dict):
            broken += 1
            continue
        if row.get("schema") not in ({SCHEMA} | PREVIOUS_SCHEMAS):
            unsupported_schema += 1
            continue
        if row.get("event") not in EVENTS:
            unknown += 1
            continue
        if (isinstance(row.get("seq"), bool)
                or not isinstance(row.get("seq"), int)
                or row["seq"] < 0
                or not _identity_claim_valid(row)):
            broken += 1
            continue
        if since and not str(row.get("ts") or "").startswith(since):
            continue
        rows.append(row)
    notes = []
    if broken:
        notes.append(f"битых строк {broken}")
    if unknown:
        notes.append(f"строк неизвестного рода {unknown}")
    if unsupported_schema:
        notes.append(f"строк неизвестной схемы {unsupported_schema}")
    return tuple(rows), ("; ".join(notes) if notes else "")


def keys_in(rows: Iterable[Mapping[str, Any]]) -> tuple[tuple[str, str], ...]:
    """Which sessions are in the journal, in order of appearance."""
    seen: list[tuple[str, str]] = []
    for row in rows:
        key = (str(row.get("device_id") or ""), str(row.get("doc_key") or ""))
        if key not in seen:
            seen.append(key)
    return tuple(seen)


def replay(rows: Iterable[Mapping[str, Any]],
           key: Sequence[str] | None = None) -> tuple[dict[str, Any], ...]:
    """Replay events into programs WITH THEIR LATEST known stage.

    Order is by `seq`, as in the live journal. A `stage` event with no
    program of its own does NOT create a ghost program: a stage without a
    body says nothing about the building, and a ghost in the list would read
    as something built.
    """
    want = (str(key[0]), str(key[1])) if key is not None else None
    programs: dict[tuple[str, str, int], dict[str, Any]] = {}
    stages: dict[tuple[str, str, int], str] = {}
    operation_ids: dict[tuple[str, str, int], list[str]] = {}
    receipt_digests: dict[tuple[str, str, int], str] = {}
    for row in rows:
        if (row.get("schema") not in ({SCHEMA} | PREVIOUS_SCHEMAS)
                or row.get("event") not in EVENTS
                or isinstance(row.get("seq"), bool)
                or not isinstance(row.get("seq"), int)
                or row["seq"] < 0
                or not _identity_claim_valid(row)):
            raise ValueError(
                "journal replay получил непроверенную семантическую строку")
        k = (str(row.get("device_id") or ""), str(row.get("doc_key") or ""))
        if want is not None and k != want:
            continue
        ident = (k[0], k[1], row["seq"])
        if row.get("event") == EVENT_PROGRAM:
            if ident in programs:
                raise ValueError("journal replay получил второе тело программы")
            programs[ident] = dict(row)
            stages[ident] = row["stage"]
            for operation_id in row.get("operation_ids") or ():
                if operation_id not in operation_ids.setdefault(ident, []):
                    operation_ids[ident].append(operation_id)
        elif row.get("event") == EVENT_OPERATION:
            if ident not in programs:
                raise ValueError(
                    "journal replay получил operation без тела программы")
            operation_id = row["operation_id"]
            if operation_id not in operation_ids.setdefault(ident, []):
                operation_ids[ident].append(operation_id)
        elif row.get("event") == EVENT_STAGE:
            if ident not in programs:
                # A stage with no body still does not spawn a ghost. It may
                # be left over from eviction/old rotation and grants no
                # authority.
                continue
            current = stages[ident]
            requested = row["stage"]
            if row.get("reconciled") is True:
                operation_id = row["operation_id"]
                digest = row["receipt_digest"]
                if (current != "running_unknown"
                        or operation_id not in operation_ids.get(ident, ())
                        or len(operation_ids.get(ident, ())) != 1):
                    raise ValueError(
                        "journal replay получил поздний commit без заранее "
                        "связанного единственного operation id в "
                        "running_unknown")
                stages[ident] = "committed"
                receipt_digests[ident] = digest
                continue
            if requested not in _STAGES:
                raise ValueError("journal replay получил неизвестную стадию")
            if current in _SIDE_STAGES:
                raise ValueError(
                    "journal replay получил переход из терминальной стадии")
            if current in _BUILT_STAGES and requested in _SIDE_STAGES:
                raise ValueError(
                    "journal replay попытался стереть доказанный эффект")
            if (requested in _MAIN_STAGES
                    and _RANK[requested] <= _RANK.get(current, 0)):
                raise ValueError(
                    "journal replay получил немонотонный переход")
            stages[ident] = requested
    out: list[dict[str, Any]] = []
    for ident in sorted(programs):
        body = programs[ident]
        if ident in stages:
            body["stage"] = stages[ident]
        if operation_ids.get(ident):
            body["operation_ids"] = list(operation_ids[ident])
        if receipt_digests.get(ident):
            body["late_receipt_digest"] = receipt_digests[ident]
        out.append(body)
    return tuple(out)


def export_program(programs: Iterable[Mapping[str, Any]], *,
                   built_only: bool = False,
                   built_stages: Sequence[str] = ("committed", "accepted"),
                   ) -> dict[str, Any]:
    """Gather the session's programs into ONE envelope `{"ops": [...]}`.

    This is the right-hand side of `tools/axes_duel.py` (`program:<file>.json`)
    and the input of `design_check.spatial_model_from_ops`.

    `built_only` is not decoration but THE HONESTY OF THE SIDE. The journal
    is filled BEFORE the write to Revit, so it also holds programs that Revit
    rejected. Comparing "what KIR DECLARED" against "what KIR BUILT" with the
    actual project are different questions, and merging them would mean
    presenting intent as construction. The default is "declared", because it
    is complete; the choice is written into the envelope as the `selection`
    field, rather than staying in the caller's head.
    """
    ops: list[dict[str, Any]] = []
    taken = 0
    skipped = 0
    for body in programs:
        if built_only and str(body.get("stage") or "") not in built_stages:
            skipped += 1
            continue
        taken += 1
        for op in (body.get("ops") or ()):
            if isinstance(op, Mapping):
                ops.append(dict(op))
    return {
        "schema": SCHEMA,
        "selection": "built" if built_only else "declared",
        "programs": taken,
        "programs_skipped": skipped,
        "ops": ops,
    }


__all__ = ["EVENTS", "EVENT_OPERATION", "EVENT_PROGRAM", "EVENT_STAGE",
           "PATH_ENV", "PREVIOUS_SCHEMAS", "SCHEMA",
           "append_line", "export_program", "keys_in", "read_events",
           "record_operation", "record_program", "record_stage", "replay",
           "store_path"]


def _bench(count: int) -> float:
    """Cost of one write, in milliseconds. Called from `--bench`."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        os.environ[PATH_ENV] = str(pathlib.Path(tmp) / "bench.jsonl")
        try:
            row = {"schema": SCHEMA, "event": EVENT_PROGRAM, "ts": _now(),
                   "device_id": "d", "doc_key": "k", "seq": 0, "stage": "planned",
                   "plan_digest": "", "author_digest": "", "intent": "",
                   "source": "bench",
                   "ops": [{"op": "create_wall", "id": f"w{i}",
                            "p0_mm": [0, i * 3000, 0], "p1_mm": [8000, i * 3000, 0]}
                           for i in range(20)]}
            started = time.perf_counter()
            for i in range(count):
                _write({**row, "seq": i})
            return (time.perf_counter() - started) * 1000.0 / count
        finally:
            os.environ.pop(PATH_ENV, None)


if __name__ == "__main__":  # pragma: no cover
    import sys
    if "--bench" in sys.argv:
        for n in (100, 1000):
            print(f"{n:5} программ: {_bench(n):.2f} мс на программу")
    else:
        rows, why = read_events()
        print(f"событий {len(rows)}; отказ: {why or 'нет'}")
