"""HOW MANY TIMES VERIFIABILITY CHANGED THE MODEL'S DECISION — a count from FEEDS.

The constitution calls this the project's main metric: "an apparatus that
does not take part in the decision was not built for this mission." Until
today there was no instrument for this in KIR at all; only the owner's
tree counted it (`tools/mission_metric.py`), and only FROM THE BENCH RUN
TAPES — and the tapes ran out on 2026-08-24 and do not appear without a
bench.

Here the source is different and it is ALWAYS written: the live service's
feeds. The definition of the event is taken from the owner verbatim and
not reinvented.

═══════════════════════════════════════════════════════════════════════════
🔴 READ THIS FIRST: THE BLOCK BELOW WAS RETRACTED ON 2026-09-02, AND
RETRACTED BY EXECUTION
═══════════════════════════════════════════════════════════════════════════

It promised: "the instrument is written so that on the day permissions
are granted it will start counting the whole thing WITHOUT A SINGLE
EDIT… it closes with READ PERMISSION on three files, not a code edit."
**The promise was wrong about its own code.** On 02.09 the permissions
were granted (`setfacl`, reading confirmed: 4061 and 1870 lines, 1518
pieces of evidence) — the instrument printed the SAME numbers and the
SAME refusal, EXIT=2. The cause: `_read` opened exactly
`kir_rejections.jsonl` and `kir_created_ids.jsonl`; the names
`kir_witness` and `kir_programs` lived ONLY in the prose and in the
message dictionary — there was no read path at all. Form 9 of this tree
(prose wider than code), and it was paid for by the very fact that the
promise's CONDITION WAS MET. Filed as `E-97` in
`/opt/kir-audit/FINDINGS.tsv`.

The block is left whole — a retracted thing is NAMED wrong, not erased —
but it must NOT be read as the instrument's current state. What stands as
of 02.09:

    flag              where it lives                        readable?
    execution         kir_witness.outcome.execution         YES (2897 lines)
    acceptance        kir_witness.outcome.acceptance        YES (2897)
    acceptance_reason kir_witness.acceptance_evidence.reason YES (1221)
    changed           kir_programs.plan_digest / ops        YES (1870)
    KIR-G* grounding  kir_rejections.jsonl                  YES, but DOES NOT JOIN

🔴 WHAT THE FEEDS STILL DO NOT GIVE TODAY — NAMED BY A NUMBER, NOT LEFT UNSAID:

  * THERE IS NO TASK BOUNDARY. The owner's `score_task` counts WITHIN ONE
    task. In the feeds, the carrier of a task is `doc_key`, and it is an
    EMPTY STRING for 100% of the lines (`programs` 1870/1870, `created`
    1733/1733). The witness chain (`prev_checksum`) is ONE continuous
    chain: exactly 1 root over 2897 lines, meaning it gives ORDER and
    does not give a split. `run_id` in the acceptance evidence is one
    line per record (1221 distinct out of 1221). So here the window is
    closed only by the NEXT DEEP SPEECH ACT, not by the end of a task,
    and the total is declared an UPPER BOUND. This is not caution:
    without a task boundary, another task's build could be credited to
    this refusal.
  * GROUNDING IS NOT PART OF THE TOTAL. `KIR-G*` lives only in
    `kir_rejections`, which has NO `plan_digest` (0 distinct over 3975
    lines); a join by `turn_id` with `kir_created_ids` gives 20 turns out
    of 589. This stream does not reach the "the program changed" flag at
    all, so grounding is counted as a POSSIBILITY and not as an EVENT.
    Named, not omitted.
  * THE NUMBER IS NOT COMPARABLE TO THE OWNER'S 17. The owner counted
    from BENCH TAPES (10 tapes, 362 rounds, tasks marked). Here the
    source is LIVE-SERVICE FEEDS, tasks are not marked, the composition
    of turns is different. Fitting one to the other is forbidden; these
    are two numbers about two different subjects.

═══════════════════════════════════════════════════════════════════════════
WHAT THE INSTRUMENT DOES COUNT, AND ONE THING THE OWNER DECLARES UNMEASURABLE
═══════════════════════════════════════════════════════════════════════════

1. POSSIBILITIES BY KIND — from refusal codes. The kind is read from the
   code's letter, and EVERY code encountered is checked against
   `kir.diag`: a code the registry does not know is a NAMED REFUSAL, not
   a quiet "other" line. Otherwise a new code would silently slip into
   the wrong bucket.
2. "REFUSAL, THEN BUILT" within one turn — by joining `kir_rejections` ×
   `kir_created_ids` on `turn_id`. This is an UPPER BOUND on events, not
   the events themselves: that the program changed SPECIFICALLY because
   of the refusal is not proven here.
3. 🔴 WHETHER THE LOCATION OF THE REFUSAL CHANGED between attempts within
   one turn — the very thing the owner's instrument writes "DOES NOT
   CHECK THE LOCATION… unverifiable on the captured tapes: the tape
   carries BARE codes with no `field_name`/`op_index`." In the feeds
   these fields DO EXIST, so the question is asked here. The answer is
   narrow and named as such: only those pairs of attempts are visible
   where BOTH left a refusal; an attempt that succeeded leaves no line in
   the refusals at all.

    PYTHONPATH=/opt/kir python -m kir.instruments.decision_changes
    PYTHONPATH=/opt/kir python -m kir.instruments.decision_changes --since 2026-08-21
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

#: Kinds of speech belonging to the MISSION. Taken from the owner's
#: `tools/mission_metric.py` verbatim: the REAL MODEL refused, not the
#: language.
DEEP_KINDS = ("свидетель", "приёмка", "заземление")
#: Kinds that any compiler with an interpreter produces. Counted
#: ALONGSIDE, not mixed in: mixing them would mean passing off the type
#: checker's work as the mission.
CHEAP_KINDS = ("тайпчекер", "песочница")
#: Reconnaissance carries a refusal code but IS NOT a refusal (the script
#: executed and wrote nothing). Paid for by the owner on 24.08, on the
#: very first run.
RECON_CODES = ("KIR-B013",)

#: Kinds whose carrier is ABSENT from the readable feeds. Not "they never
#: happened" — there is NOTHING TO SEE THEM WITH. The list is closed and
#: named, so the report does not pass off blindness as zero.
BLIND_DEEP_KINDS = ("свидетель", "приёмка")
#: Carriers of the invisible half: file -> what it holds.
UNREADABLE_CARRIERS = {
    "kir_witness.jsonl": "execution (свидетель) и acceptance (приёмка)",
    "kir_programs.jsonl": "тело программы — единственный носитель признака «изменилась»",
    "../evidence/kir_acceptance/": "журнал приёмки",
}


class FeedRefusal(RuntimeError):
    """The source is unavailable or incomplete. The measurement DID NOT HAPPEN."""


@dataclass
class Census:
    turns_refused: int = 0
    turns_built: int = 0
    turns_refused_then_built: int = 0
    deep_then_built: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    attempts_pairs: int = 0
    place_changed: int = 0
    place_repeated: int = 0
    unknown_codes: set[str] = field(default_factory=set)
    window: tuple[str, str] = ("", "")
    rows_refused: int = 0
    rows_created: int = 0


#: Feed file -> {line number: why it is not a feed line}. Filled by
#: `_read`, printed BEFORE the numbers by both reports.
#:
#: 🔴 SET UP 2026-09-04 (RT-19). `_read` used to have a silent
#: `except ValueError: continue`: a broken line vanished from the tape
#: WITHOUT A TRACE, and every share this instrument computes ("deep out
#: of possibilities", "refusal, then built") was taken from what
#: remained. Their denominator is the NUMBER OF TAPE LINES, meaning the
#: share GREW exactly because part of the tape was lost, while the
#: report line "lines: N refusals" kept looking like a complete census.
#:
#: The verdict is unchanged — a live tape's measurement must not be
#: dropped over a single broken line, the feed is being appended to
#: exactly while it is being read, and a torn tail is ordinary business
#: here — but the loss now has a NUMBER, a FILE NAME, and a LINE NUMBER.
_BROKEN_LINES: "dict[str, dict[int, str]]" = {}


def broken_feed_lines() -> "dict[str, dict[int, str]]":
    """What `_read` failed to parse during this run. Empty means everything parsed."""
    return {name: dict(rows) for name, rows in _BROKEN_LINES.items() if rows}


def _read(path: pathlib.Path) -> list[dict]:
    """Feed lines. An unreadable file is a NAMED refusal, not an empty
    list.

    A broken LINE is also a named fact: it goes into `_BROKEN_LINES` and
    is printed BEFORE the numbers (`broken_feed_lines()`), rather than
    dissolving into them.
    """
    if not path.exists():
        raise FeedRefusal(f"фида нет: {path}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except PermissionError as exc:
        raise FeedRefusal(
            f"фид {path.name} НЕ ЧИТАЕТСЯ этим пользователем: {exc}. "
            "Пустой список отсюда был бы фактом о правах, а не о ходах") from exc
    out = []
    битые = _BROKEN_LINES.setdefault(path.name, {})
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            битые[lineno] = f"{type(exc).__name__}: {exc}"
            continue
        if not isinstance(record, dict):
            # It parsed, but it is not a tape line. Previously such a line
            # went into the count on a par with real ones and failed later
            # — on `.get`.
            битые[lineno] = (f"строка разобралась, но это "
                             f"{type(record).__name__}, а не запись фида")
            continue
        out.append(record)
    return out


def speech_kind(code: str | None, known_codes: frozenset[str],
                unknown: set[str]) -> str:
    """WHAT EXACTLY spoke. The order of branches is the owner's.

    🔴 A code `kir.diag` DOES NOT KNOW does not silently slip into
    "other": it accumulates in `unknown` and is printed as a separate
    line. A new code landing in the wrong bucket is a counting error that
    looks like a count.
    """
    c = str(code or "")
    if not c:
        return "отказ БЕЗ кода"
    if known_codes and c not in known_codes:
        unknown.add(c)
    if c in RECON_CODES:
        return "разведка"
    if c.startswith("KIR-A"):
        return "приёмка"
    if c.startswith("KIR-G"):
        return "заземление"
    if c.startswith("KIR-B"):
        return "песочница"
    if c.startswith(("KIR-T", "KIR-P", "KIR-L", "KIR-V")):
        return "тайпчекер"
    return "прочее"


def _known_codes() -> frozenset[str]:
    """Codes declared by the registry. Empty — nothing to check against,
    and this is said.

    🔴 THE TABLE IS ASKED, NOT THE MODULE'S NAMES (measured 2026-09-04). A
    scan of `dir(diag)` for string constants shaped like `KIR-XXXX` used
    to stand here, and it was a SECOND carrier of the code registry.
    Since 01.09 (`adef3a8`) codes are registered with
    `diag.register(...)` and are NOT REQUIRED to be a module constant:

        by a scan of module names   68
        in the `CODES` table       107
        invisible to the scan       39   a strict subset: the scan knew
                                          of NOT A SINGLE code beyond the
                                          table

    The cost was not in the count, but in the ACCUSATION: the instrument
    printed «КОДЫ, КОТОРЫХ НЕ ЗНАЕТ `kir.diag`: KIR-G101, KIR-G102,
    KIR-G104, KIR-M003, KIR-M006» — all five are registered and alive,
    two of them are issued by prod dozens of times a day. A line that
    sends someone to fix what is already fixed is more costly than a
    missing one.

    The name scan remains as a FALLBACK and is named as such: an
    installation older than the table still has to check itself against
    something.
    """
    try:
        from kir import diag
    except ImportError:
        return frozenset()
    таблица = getattr(diag, "CODES", None)
    if таблица:
        return frozenset(str(код) for код in таблица)
    found = set()
    for name in dir(diag):
        value = getattr(diag, name, None)
        if isinstance(value, str) and value.startswith("KIR-") and len(value) == 8:
            found.add(value)
    return frozenset(found)


# ───────────────────────────────────────────────────────────────────────────
# THE DEFINITION OF THE EVENT — VERBATIM FROM THE OWNER.
#
# Source: `/opt/kukai-rebuild1/backend/tools/mission_metric.py` (the
# OWNER's tree, read 2026-09-02). The four functions below are its
# `speech_kind`, `spoke`, `is_deep`, `_changed`, and the body of
# `score_task`, carried over WITHOUT any change of meaning. It cannot be
# taken by import: the KIR↔product boundary is held by zero top-level
# product imports, and it must not be broken for the sake of an
# instrument. Hence the copy — and hence the source is named here, not in
# someone's memory.
#
# The only thing of our own here is the `_rounds_from_witness` adapter: it
# brings a feed line into the line shape these functions expect.
# ───────────────────────────────────────────────────────────────────────────

#: Acceptance refuses with two codes: `KIR-A006` — "re-read and DID NOT
#: AGREE", `KIR-A007` — "could not re-read". The owner's split, not ours.
_ACCEPTANCE_REJECTED = ("rejected",)
#: Reasons acceptance failed to finish reading ITS OWN subject, not the
#: world. Counting its own blindness as verifiability speaking would mean
#: recording it as a mission event.
_BLIND_REASONS = ("partial_blind_scope", "vacuous")


def speech_kind_row(rd: Mapping[str, Any]) -> str:
    """WHAT EXACTLY spoke on this turn. The order of the branches carries
    meaning: a rollback outranks any code, because it means "the real
    model did not accept what was written". A copy of the owner's
    `speech_kind`."""
    if rd.get("execution") == "rolled_back":
        return "свидетель"
    codes = [str(c or "") for c in (rd.get("codes") or [])]
    if rd.get("acceptance") in _ACCEPTANCE_REJECTED or "KIR-A006" in codes:
        return "приёмка"
    if rd.get("acceptance") == "inconclusive" or "KIR-A007" in codes:
        reason = str(rd.get("acceptance_reason") or "")
        return ("приёмка слепа" if reason in _BLIND_REASONS
                else "приёмка не дочитала")
    if any(c.startswith("KIR-G") for c in codes):
        return "заземление"
    if codes and all(c in RECON_CODES for c in codes):
        return "разведка"
    if any(c.startswith("KIR-B") for c in codes):
        return "песочница"
    if any(c.startswith(("KIR-T", "KIR-P", "KIR-L", "KIR-V")) for c in codes):
        return "тайпчекер"
    if rd.get("refused"):
        return "отказ БЕЗ кода"
    return "нет"


def spoke(rd: Mapping[str, Any]) -> bool:
    """Whether verifiability spoke on this turn — of any kind."""
    return bool(
        rd.get("refused")
        or rd.get("execution") == "rolled_back"
        or rd.get("acceptance") in ("rejected", "inconclusive")
        or any(str(c or "").startswith("KIR-A")
               for c in (rd.get("codes") or []))
    )


def is_deep(rd: Mapping[str, Any]) -> bool:
    """Whether the REAL MODEL refused, not the language."""
    return spoke(rd) and speech_kind_row(rd) in DEEP_KINDS


def _changed(rd: Mapping[str, Any]):
    """Whether the turn's program differs from the previous one. None =
    NOT RECORDED.

    "No" and "not recorded" are different facts, and the second has no
    right to be silently counted as the first (the owner's rule, kept
    verbatim).
    """
    if "changed" in rd:
        value = rd["changed"]
        return None if value is None else bool(value)
    return None


def score_stream(rounds: list[dict]) -> dict:
    """Turns of ONE tape -> mission events.

    🔴 THE DIFFERENCE FROM THE OWNER, NAMED, NOT HIDDEN: for the owner
    this is `score_task`, and the tape is split into TASKS. Here there is
    no task boundary — `doc_key` is empty for 100% of the feed's lines,
    the witness chain is one continuous chain. So the window is closed
    only by the next DEEP speech act, and the total is an UPPER BOUND: a
    neighboring task's build could be credited to this refusal. The
    algorithm otherwise matches the owner's, line for line.
    """
    events, ambiguous, deep, opportunities = [], [], 0, 0
    by_kind: dict[str, int] = {}
    for i, rd in enumerate(rounds):
        if not spoke(rd):
            continue
        kind = speech_kind_row(rd)
        opportunities += 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if kind not in DEEP_KINDS:
            continue
        deep += 1
        seen_change = None
        for j in range(i + 1, len(rounds)):
            if is_deep(rounds[j]):
                break
            if _changed(rounds[j]):
                seen_change = True
            if rounds[j].get("built"):
                rec = {"round": rd.get("n"), "kind": kind,
                       "built_at": rounds[j].get("n"), "after_rounds": j - i}
                (events if seen_change else ambiguous).append(rec)
                break
    return {"opportunities": opportunities, "deep": deep,
            "by_kind": by_kind, "events": events, "ambiguous": ambiguous}


def _rounds_from_witness(rows: list[dict]) -> list[dict]:
    """Lines of `kir_witness.jsonl` -> turns in the owner's shape.

    THIS IS THE ONLY PLACE WHERE THE FEED'S SHAPE MEETS THE DEFINITION.
    The fields are not guessed, they were taken from the feed on 02.09
    (4061 lines):

        outcome.execution   read_completed · committed · unconfirmed · rolled_back
        outcome.acceptance  not_applicable · accepted · not_run · inconclusive · rejected
        outcome.witness     satisfied · incomplete · violated
        acceptance_evidence.reason   carries `partial_blind_scope` (174 lines)
        diag_code           only KIR-X* and KIR-A* — grounding is NOT here
        plan_digest         the plan's signature; a signature change is exactly "the program changed"

    Order is taken by `ts`: the `prev_checksum` chain gives the same
    order and adds nothing to it (root 1, break 0 — verified).
    """
    ordered = sorted(rows, key=lambda r: str(r.get("ts", "")))
    out: list[dict] = []
    prev_plan: str | None = None
    for n, r in enumerate(ordered, 1):
        outcome = r.get("outcome")
        outcome = outcome if isinstance(outcome, Mapping) else {}
        evidence = r.get("acceptance_evidence")
        evidence = evidence if isinstance(evidence, Mapping) else {}
        plan = str(r.get("plan_digest") or "") or None
        # THE CARRIER OF A TASK. Asked by name, not inferred: an empty
        # string is not a task, and substituting anything for it (a
        # device, a family, a time window) would mean establishing a
        # convention instead of an authority. Today this field is absent
        # from the witness tape entirely.
        task = str(r.get("doc_key") or "") or None
        # "Changed" = the plan's signature differs from the previous
        # turn's signature. No signature — NOT RECORDED (None), not "no":
        # the owner's rule.
        changed = None if (plan is None or prev_plan is None) else (plan != prev_plan)
        code = str(r.get("diag_code") or "")
        out.append({
            "n": n,
            "ts": str(r.get("ts") or ""),
            "execution": outcome.get("execution"),
            "acceptance": outcome.get("acceptance"),
            "acceptance_reason": evidence.get("reason"),
            "codes": [code] if code else [],
            "refused": bool(code) or r.get("ok") is False,
            "changed": changed,
            "built": outcome.get("execution") == "committed",
            "plan_digest": plan,
            "task": task,
        })
        if plan is not None:
            prev_plan = plan
    return out


@dataclass
class Mission:
    """The total by the owner's definition, on the witness tape."""
    rows: int = 0
    rounds: int = 0
    opportunities: int = 0
    deep: int = 0
    events: int = 0
    ambiguous: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    window: tuple[str, str] = ("", "")
    programs_rows: int = 0
    programs_digests: int = 0
    evidence_files: int = 0
    #: 🔴 THE INSTRUMENT'S OWN CONTROL, not a separate outside run.
    #: `upper_bound` — the count when the "changed" flag is declared true
    #: ALWAYS. If it equals `events`, the flag distinguishes NOTHING, and
    #: the "events" number is an upper bound wearing a metric's costume
    #: (form 14: a quantity identical under both outcomes measures
    #: neither).
    upper_bound: int = 0
    changed_true: int = 0
    changed_false: int = 0
    changed_unknown: int = 0

    @property
    def discriminated(self) -> int:
        """How much the "changed" flag moved the count. 0 = INERT."""
        return self.upper_bound - self.events

    #: Distinct TASKS found in the tape. Zero = there is no split at all.
    task_keys: int = 0
    #: 🔴 COMPUTED, NOT ASSERTED. A phrase HARDCODED AS TEXT used to stand
    #: here — "`doc_key` is empty for 100% of lines" — and on 02.09 it
    #: became untrue the very hour the producer was fixed: a live turn
    #: gave the first non-empty ones. An instrument asserting about its
    #: own input something it is capable of counting is our own named
    #: class (prose wider than code) working against itself, inside the
    #: instrument.
    docs_named: int = 0
    docs_total: int = 0

    @property
    def definition_holds(self) -> bool:
        """Whether `events` can be called the mission's total.

        🔴 THE CRITERION IS STRUCTURAL, NOT A THRESHOLD, AND THIS WAS PAID
        FOR ON 02.09. The first edition asked "does the flag distinguish
        anything at all" with a one-percent threshold — the threshold was
        MADE UP, and it let 1.2% through, meaning a degenerate
        distinguisher would have slid by under the metric's name. A gate
        invented by the author is more costly than a missing one.

        What is asked is what the definition requires: a TASK window. If
        the tape has not a single distinguishable task, there is NOTHING
        to count by this definition — regardless of what number came out.
        Tuning a threshold to fit the desired answer is impossible here BY
        CONSTRUCTION: the quantity is not compared to anything.
        """
        return self.task_keys > 0


def mission(feed_dir: pathlib.Path, since: str = "") -> Mission:
    """The mission count from the witness. An unreadable carrier is a NAMED refusal."""
    rows = _read(feed_dir / "kir_witness.jsonl")
    if since:
        rows = [r for r in rows if str(r.get("ts", "")) >= since]
    if not rows:
        raise FeedRefusal(
            "в окне нет ни одной строки свидетеля. Замер миссии НЕ СОСТОЯЛСЯ: "
            "«ноль событий» и «нечего считать» — разные факты")
    rounds = _rounds_from_witness(rows)
    s = score_stream(rounds)
    # 🔴 A CONTROL INSIDE THE INSTRUMENT: the same count with the
    # "changed" flag declared true ALWAYS. If the two numbers match, the
    # flag distinguishes nothing and "event" is an upper bound.
    inert = score_stream([dict(r, changed=True) for r in rounds])
    stamps = [r["ts"] for r in rounds if r["ts"]]
    m = Mission(
        rows=len(rows), rounds=len(rounds),
        opportunities=s["opportunities"], deep=s["deep"],
        events=len(s["events"]), ambiguous=len(s["ambiguous"]),
        by_kind=s["by_kind"],
        upper_bound=len(inert["events"]),
        changed_true=sum(1 for r in rounds if r["changed"] is True),
        changed_false=sum(1 for r in rounds if r["changed"] is False),
        changed_unknown=sum(1 for r in rounds if r["changed"] is None),
        task_keys=len({r["task"] for r in rounds if r["task"]}),
        window=(min(stamps), max(stamps)) if stamps else ("", ""))
    # Programs and acceptance evidence are read NOT for the count, but so
    # that "the carrier exists" is not confused with "the carrier was
    # read". A refusal of either is loud.
    progs = _read(feed_dir / "kir_programs.jsonl")
    m.programs_rows = len(progs)
    m.docs_total = len(progs)
    m.docs_named = sum(1 for p in progs if str(p.get("doc_key") or ""))
    m.programs_digests = len({str(p.get("plan_digest")) for p in progs
                              if p.get("plan_digest")})
    evidence_dir = feed_dir.parent / "evidence" / "kir_acceptance"
    if not evidence_dir.is_dir():
        raise FeedRefusal(
            f"журнала приёмки нет по пути {evidence_dir}. "
            "Считать без него значило бы объявить слепоту нулём")
    try:
        m.evidence_files = sum(1 for _ in evidence_dir.iterdir())
    except PermissionError as exc:
        raise FeedRefusal(
            f"журнал приёмки {evidence_dir} НЕ ЧИТАЕТСЯ: {exc}") from exc
    return m


def census(feed_dir: pathlib.Path, since: str = "") -> Census:
    """Reconcile the readable feeds. Do NOT guess at the invisible half."""
    rej = _read(feed_dir / "kir_rejections.jsonl")
    cre = _read(feed_dir / "kir_created_ids.jsonl")
    if since:
        rej = [r for r in rej if str(r.get("ts", "")) >= since]
        cre = [r for r in cre if str(r.get("ts", "")) >= since]
    if not rej:
        raise FeedRefusal(
            "в окне нет ни одной строки отказа. Замер НЕ СОСТОЯЛСЯ: "
            "«ноль событий» и «нечего считать» — разные факты")

    known = _known_codes()
    out = Census(rows_refused=len(rej), rows_created=len(cre))
    stamps = [str(r.get("ts", "")) for r in rej if r.get("ts")]
    out.window = (min(stamps), max(stamps)) if stamps else ("", "")

    by_turn: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rej:
        if r.get("turn_id"):
            by_turn[str(r["turn_id"])].append(r)
    built_turn: dict[str, list[dict]] = collections.defaultdict(list)
    for r in cre:
        if r.get("turn_id") and (r.get("created_count") or 0) > 0:
            built_turn[str(r["turn_id"])].append(r)

    out.turns_refused = len(by_turn)
    out.turns_built = len(built_turn)
    kinds: collections.Counter = collections.Counter()

    for turn, rows in by_turn.items():
        rows = sorted(rows, key=lambda r: str(r.get("ts", "")))
        kind = speech_kind(rows[0].get("diag_code"), known, out.unknown_codes)
        kinds[kind] += 1

        builds = [b for b in built_turn.get(turn, ())
                  if str(b.get("ts", "")) > str(rows[0].get("ts", ""))]
        if builds:
            out.turns_refused_then_built += 1
            if kind in DEEP_KINDS:
                out.deep_then_built += 1

        seen: list[tuple[str, tuple]] = []
        for r in rows:
            attempt = r.get("attempt_id")
            if attempt and attempt not in [a for a, _ in seen]:
                seen.append((attempt, (r.get("diag_code"),
                                       r.get("op_id"), r.get("field_name"))))
        if len(seen) >= 2:
            out.attempts_pairs += 1
            if len({place for _a, place in seen}) > 1:
                out.place_changed += 1
            else:
                out.place_repeated += 1

    out.by_kind = dict(kinds)
    return out


def render(c: Census, feed_dir: pathlib.Path) -> str:
    deep = sum(n for k, n in c.by_kind.items() if k in DEEP_KINDS)
    cheap = sum(n for k, n in c.by_kind.items() if k in CHEAP_KINDS)
    lines = [
        "ПРОВЕРЯЕМОСТЬ ПРОТИВ РЕШЕНИЯ МОДЕЛИ — ПО ЧИТАЕМЫМ ФИДАМ",
        f"предмет: {feed_dir}",
        f"окно:    {c.window[0][:19] or '—'} … {c.window[1][:19] or '—'}",
        f"строк:   отказов {c.rows_refused} · созданий {c.rows_created}",
        "",
        f"  ходов с отказом                 {c.turns_refused:6d}",
        f"  ходов с постройкой              {c.turns_built:6d}",
        f"  «отказ, потом построено»        {c.turns_refused_then_built:6d}   "
        "ВЕРХНЯЯ ГРАНИЦА событий, не события",
        f"     из них ГЛУБОКИЙ род          {c.deep_then_built:6d}",
        "",
        "  возможности по роду речи:",
    ]
    for kind, n in sorted(c.by_kind.items(), key=lambda kv: -kv[1]):
        tag = "ГЛУБОКИЙ" if kind in DEEP_KINDS else (
            "мелкий" if kind in CHEAP_KINDS else "не речь")
        lines.append(f"     {kind:16s} {n:5d}   {tag}")
    lines += [
        f"     ── глубоких {deep}, мелких {cheap}",
        "",
        "  МЕСТО ОТКАЗА между попытками одного хода "
        "(хозяйский прибор это не умеет):",
        f"     пар попыток, обе с отказом   {c.attempts_pairs:6d}",
        f"     место ИЗМЕНИЛОСЬ             {c.place_changed:6d}",
        f"     то же место повторено        {c.place_repeated:6d}",
        "",
        "🔴 ЭТОТ ПОТОК В ИТОГ МИССИИ НЕ ВХОДИТ, И ВОТ ПОЧЕМУ.",
        "   `kir_rejections` НЕ несёт `plan_digest` (0 различных), поэтому",
        "   признака «программа изменилась» отсюда не достать; соединение с",
        "   `kir_created_ids` по `turn_id` покрывает лишь часть ходов. Значит",
        "   заземление считается ВОЗМОЖНОСТЬЮ и не считается СОБЫТИЕМ.",
        "   Итог миссии печатается НИЖЕ, по ленте свидетеля.",
    ]
    if c.unknown_codes:
        lines += [
            "",
            "🔴 КОДЫ, КОТОРЫХ НЕ ЗНАЕТ `kir.diag` (род присвоен по букве, "
            "сверить нечем):",
            "   " + ", ".join(sorted(c.unknown_codes)),
        ]
    return "\n".join(lines)


def render_mission(m: Mission) -> str:
    deep_seen = sum(n for k, n in m.by_kind.items() if k in DEEP_KINDS)
    lines = [
        "",
        "═" * 74,
        "ИТОГ МИССИИ — ПО ЛЕНТЕ СВИДЕТЕЛЯ, ОПРЕДЕЛЕНИЕ ХОЗЯИНА ДОСЛОВНО",
        "═" * 74,
        f"носители:  свидетель {m.rows} строк · программы {m.programs_rows} "
        f"({m.programs_digests} подписей) · улик приёмки {m.evidence_files}",
        f"окно:      {m.window[0][:19] or '—'} … {m.window[1][:19] or '—'}",
        "",
        f"  ходов в ленте                   {m.rounds:6d}",
        f"  возможностей (речь любого рода) {m.opportunities:6d}",
        f"  из них ГЛУБОКИХ                 {m.deep:6d}",
        "",
        "  по роду речи:",
    ]
    for kind, n in sorted(m.by_kind.items(), key=lambda kv: -kv[1]):
        tag = "← миссия" if kind in DEEP_KINDS else ""
        lines.append(f"     {kind:20s} {n:5d}   {tag}")
    lines += [
        "",
        f"  «глубокая речь -> ПОСТРОЕНО»    {m.upper_bound:6d}   "
        "ВЕРХНЯЯ ГРАНИЦА, не события",
        f"  из них признак «ИЗМЕНИЛОСЬ» отсёк {m.discriminated:4d}   "
        f"осталось {m.events}",
        "",
        "🔴 СОБСТВЕННЫЙ КОНТРОЛЬ ПРИБОРА (не отдельный прогон снаружи):",
        f"     признак «изменилось»: ДА {m.changed_true} · НЕТ {m.changed_false}"
        f" · НЕ ЗАПИСАНО {m.changed_unknown}",
        f"     тот же счёт с признаком, истинным ВСЕГДА: {m.upper_bound}",
        f"     РАЗЛИЧАЮЩАЯ СИЛА: {m.discriminated} из {m.upper_bound}"
        + (f" ({100 * m.discriminated / m.upper_bound:.1f} %)"
           if m.upper_bound else ""),
    ]
    if m.definition_holds:
        lines += [
            "",
            f"  СОБЫТИЙ МИССИИ                  {m.events:6d}",
            f"  спорных (изменение не записано) {m.ambiguous:6d}",
        ]
    else:
        lines += [
            "",
            "🔴 ИТОГ МИССИИ НЕ ОБЪЯВЛЯЕТСЯ, И ЭТО ОТВЕТ, А НЕ МОЛЧАНИЕ.",
            f"   Определение хозяина считает В ПРЕДЕЛАХ ОДНОЙ ЗАДАЧИ. Различимых",
            f"   задач в ленте: {m.task_keys}. Носитель задачи — `doc_key` —",
            f"   назван у {m.docs_named} строк из {m.docs_total} в `kir_programs`.",
            "   Без границы задачи признак",
            "   «изменилось» вырождается: подпись плана отличается почти у каждой",
            f"   соседней пары, поэтому он отсекает {m.discriminated} из"
            f" {m.upper_bound}.",
            "   Величина, почти одинаковая при обоих исходах признака, не меряет",
            "   ни одного из них — печатать её как «события миссии» значило бы",
            "   надеть на верхнюю границу имя метрики.",
            "",
            "   🔴 ЧТО ЗАКРЫВАЕТ — И ЭТО НЕ ПРОИЗВОДИТЕЛЬ: он несёт документ",
            "   с 30.08.2026 (`serving.py`: plan_stream.publish(doc_key=…),",
            "   коммит c9c17c5). Пусто — в строках, написанных ДО того дня;",
            "   фид молчал с 27.08 по 02.09. Закрывают ЖИВЫЕ ХОДЫ после",
            "   починки: нужно столько, чтобы в ОДНОЙ задаче встретились",
            "   отказ и последующая постройка. Отправлять чинить починенное",
            "   — заниженный предел, читаемый как «этого нет».",
        ]
    lines += [
        "",
        "🔴 ГРАНИЦЫ ЧИСЕЛ ВЫШЕ — ЧАСТЬ ЧИСЕЛ, А НЕ ОГОВОРКА ПОД НИМИ:",
        "   1. ЗАЗЕМЛЕНИЕ СЮДА НЕ ВХОДИТ: `KIR-G*` живёт в `kir_rejections`, а тот",
        "      не несёт подписи плана. Его счёт — в блоке выше, как возможность.",
        "   2. С ХОЗЯЙСКИМИ 17 НЕ СРАВНИВАТЬ: там ленты стенда с размеченными",
        "      задачами, здесь фиды живой службы. Два числа о двух предметах.",
        "   3. РОДА, КОТОРЫЕ ТЕПЕРЬ ВИДНЫ ВПЕРВЫЕ: свидетель и приёмка. До 02.09",
        "      их носитель не читался вовсе, и прибор объявлял их невидимыми.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kir.instruments.decision_changes",
        description=__doc__.split("\n", 1)[0])
    ap.add_argument("--feeds", default="", metavar="ДИР",
                    help="каталог фидов; по умолчанию спрашивается у порта")
    ap.add_argument("--since", default="", metavar="ISO",
                    help="нижняя граница окна, напр. 2026-08-21")
    ap.add_argument("--partial", action="store_true",
                    help="признать неполноту и вернуть 0")
    args = ap.parse_args(argv)

    if args.feeds:
        feed_dir = pathlib.Path(args.feeds)
    else:
        from kir.install_paths import install_data_path
        found = install_data_path("telemetry")
        if found is None:
            print("🔴 ЗАМЕР НЕ СОСТОЯЛСЯ: каталог фидов не назван — "
                  "ни `--feeds`, ни порт `data.install_paths` его не дают.")
            print("   Это факт О СРЕДЕ, а не «событий ноль».")
            return 2
        feed_dir = pathlib.Path(found)

    # The grounding stream (refusals × created). Its refusal is the loss
    # of a PART, and that loss is named; the mission's total rests on a
    # different carrier and does not depend on it.
    try:
        c = census(feed_dir, since=args.since)
        print(render(c, feed_dir))
    except FeedRefusal as exc:
        print(f"🔴 ПОТОК ЗАЗЕМЛЕНИЯ НЕ ПРОЧИТАН: {exc}")
        print("   Итог миссии ниже стоит на ленте свидетеля и этим не задет.")

    # The mission's total. Its refusal is THE MEASUREMENT DID NOT HAPPEN,
    # and no zero is printed here.
    try:
        m = mission(feed_dir, since=args.since)
    except FeedRefusal as exc:
        print(f"\n🔴 ИТОГ МИССИИ НЕ ПОСЧИТАН: {exc}")
        print("   Это факт О НОСИТЕЛЕ, а не «событий ноль».")
        return 2
    print(render_mission(m))
    # 🔴 THE LOSS IS NAMED NEXT TO THE NUMBERS, NOT BELOW THEM (RT-19). It
    # is printed AFTER both reports only because before the feeds are
    # read it does not exist yet: the very count of broken lines is
    # assembled by exactly the reading that produced the numbers.
    битые = broken_feed_lines()
    if битые:
        всего = sum(len(rows) for rows in битые.values())
        print(f"\n🔴 СТРОК ФИДОВ НЕ РАЗОБРАЛОСЬ: {всего} "
              f"в {len(битые)} файле(ах) — числа выше сняты БЕЗ них")
        for имя, rows in sorted(битые.items()):
            print(f"   · {имя}: {len(rows)} строк(и)")
            for номер, почему in sorted(rows.items())[:3]:
                print(f"       строка {номер}: {почему[:88]}")
            if len(rows) > 3:
                print(f"       … и ещё {len(rows) - 3}")
    # 🔴 THREE OUTCOMES, THREE CODES — otherwise "did not judge" is
    # indistinguishable from "judged and it came out this way".
    #   0  the mission's total is declared
    #   2  the carrier was not read: THE MEASUREMENT DID NOT HAPPEN (a
    #      fact about the environment)
    #   3  the carriers were read, but the definition cannot be carried
    #      out on this data (no task boundary; a degenerate
    #      distinguisher) — the instrument DID NOT JUDGE
    return 0 if m.definition_holds else 3


if __name__ == "__main__":
    sys.exit(main())
