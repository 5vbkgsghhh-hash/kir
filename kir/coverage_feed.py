"""KIR rejection telemetry — producer side of the coverage flywheel
(SPEC §14.1; contract: the host's KIR queue contract, schema v1).

Every refusal is a growth signal. Events are appended (JSONL, fail-open —
a write failure never blocks compilation) to the contract path; the cube's
coverage_queue consumer joins them by query_id and ranks the holes.

Contract essentials honoured here:
  * kind_requested is the RAW string the model emitted — never normalized;
    invented names ARE the signal (the OST_ImportInstances lesson);
  * reject_code is the closed enum from the contract;
  * query texts live in rag_retrieval.jsonl — we only carry query_id;
  * diag_code and candidates ride BESIDE the enum (added 2026-08-09, additive
    to schema v1): without them a CORRECT grounding refusal — the compiler
    declining to choose for the author and naming candidates instead — was
    indistinguishable from an author error in every later count. Measured
    damage: 662 of 1469 stored events were correct refusals filed as generic
    VALIDATION_FAILED. See the block above _MAX_CANDIDATES.
  * op_id and field_name ride beside them (added 2026-08-09, same additivity):
    a refusal must be identifiable from the corpus alone, and «op_requested»
    names the OP KIND while the diagnostic already knew the instance and the
    field. Both were being discarded at this exact line.
"""
# 🔴 PROVENANCE MOVED OUT OF THE DOCSTRING 01.09.2026 — A DOOR VERSUS A
# JOURNAL. A module's docstring is a PUBLIC DOOR: `help()` prints it to a
# reader of the published package, and our machine's address tells them
# nothing. The knowledge is not erased — it is here, in the journal, where
# it belongs:
#     queue contract  /root/kukai-cube/KIR_QUEUE_CONTRACT.md (schema v1)
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
from kir import env  # noqa: E402  (a submodule with no dependencies — creates no cycle)
import uuid
from datetime import datetime, timezone
from typing import Optional

from kir.install_paths import install_data_path

logger = logging.getLogger(__name__)

_ENV = "KIR_REJECTIONS_PATH"
# §18.5: the absence of a path = the function is DISABLED, not a write
# into someone else's filesystem. This used to hold an absolute path
# belonging to this install, and on a different machine the very first
# compiler refusal would try to create /opt/kukai-rebuild1/... .
_DEFAULT = None
# The fallback is left in place precisely because KIR_REJECTIONS_PATH is
# absent from the prod .env (checked 28.07), and this wave must not touch
# .env: without it, rejection telemetry on prod would fall silent, and
# silently. The test used to be isdir() on the absolute path — that is,
# "the path exists ON THE MACHINE", not "we were run from it"; a
# measurement on 02.08 showed that a process from a worktree resolved to
# the PROD file. Now the address belongs to the install the module was
# imported from (install_paths).
_MAX_EVENTS_PER_COMPILE = 10

# diag code -> contract reject_code
_REJECT_BY_DIAG = {
    "KIR-G001": "UNSUPPORTED_KIND",
    "KIR-G002": "SLOT_RESOLUTION_FAILED",
}
_FALLBACK_REJECT = "VALIDATION_FAILED"

# ─── A REFUSAL MUST KEEP ITS IDENTITY ────────────────────────────────────
#
# `reject_code` is a CLOSED contract enum (KIR_QUEUE_CONTRACT.md, v1), and
# it must not be extended: the `coverage_queue.py` consumer ranks coverage
# gaps precisely by it. But collapsing EVERYTHING that is not G001/G002
# into `VALIDATION_FAILED` cost exactly what the feed was built for.
#
# Measured 09.08.2026 over `kir_rejections.jsonl` (1469 events, 16.07–04.08):
# 1364 of them are `VALIDATION_FAILED`, and inside that pile lie TWO
# DIFFERENT WORLDS:
#
#   662 events — a CORRECT REFUSAL. The compiler refused to choose on the
#       author's behalf and named candidates: 604 ambiguities (`KIR-G102` —
#       «несколько вариантов, default невозможен»), 49 "name not found"
#       with nearest matches (`KIR-G101`), 9 honestly empty pools
#       (`KIR-G104`). This is the compiler DOING ITS JOB — the very
#       behavior behind why a live pairing on 02.08 showed the C# arm
#       silently taking 1 door type out of 62, while KIR refused;
#   the rest — an author error (parsing, types, program budget).
#
# Both piles were counted the same way — "a refusal" — and a correct
# refusal went into the statistics as a defect. Now TWO fields ride
# alongside the contractual `reject_code`:
#
#   `diag_code`  — the original typed code (`KIR-G102`, `KIR-T002`, …);
#   `candidates` — what the compiler OFFERED instead of choosing for the
#                  author. There is no such thing as an empty candidate
#                  list on a refusal that has candidates; its presence is
#                  itself the proof that the refusal is correct.
#
# Both fields are ADDITIVE to schema v1: the consumer reads by key, and
# old events without them stay readable (their class is recovered from the
# `detail` text — see `tools/live_op_rates.py`, the "by text" columns).
_MAX_CANDIDATES = 8


def _candidates(diag) -> list:
    """Refusal candidates, trimmed and stripped down to {id, name}.

    There are no coordinates here and never were; we take exactly the
    fields the author can use to rewrite the selector
    (`{"by": "element_id", "value": <id>}`)."""
    raw = getattr(diag, "candidates", None)
    if not isinstance(raw, list) or not raw:
        return []
    out = []
    for item in raw[:_MAX_CANDIDATES]:
        if isinstance(item, dict):
            row = {k: item[k] for k in ("id", "name") if k in item}
            out.append(row or {k: str(v)[:64] for k, v in list(item.items())[:2]})
        else:
            out.append({"name": str(item)[:64]})
    return out

# op name -> action (op_requested field)
_ACTION_BY_OP = {"query_count": "count", "query_list": "list", "query_inspect": "inspect"}

# best-effort kind -> cube object_kind axis (cell is nullable by contract)
_OBJECT_KIND_HINTS = {
    "cad_link": "link", "rvt_link": "link", "level": "level",
    "view": "view", "sheet": "sheet", "grid": "grid", "room": "room_space",
}


def _cell(action: Optional[str], kind: Optional[str]) -> Optional[str]:
    if not action:
        return None
    ok = _OBJECT_KIND_HINTS.get(kind or "", "element")
    return f"{action}×{ok}"


def _feed_path() -> Optional[str]:
    """Where to write rejection telemetry, or None — "the feed is off".

    Order: env ⇒ THIS install's data directory ⇒ None. Outside the source
    tree, the last step is silence, not an attempt to create someone
    else's directory.
    """
    path = env.get(_ENV)
    if path:
        return path
    if path is None:
        owned = install_data_path("telemetry", "kir_rejections.jsonl")
        if owned is not None:
            return str(owned)
    return _DEFAULT


def record_rejections(
    diagnostics: list,
    ops: list,
    query_id: str = "",
    revit_version: str = "2026",
    stage: str = "compile",
    *,
    turn_id: str = "",
    action_id: str = "",
    query_fingerprint: str = "",
    source_kind: str = "unknown",
) -> None:
    """diagnostics: list[kir.diag.Diagnostic]; ops: raw program ops (may be junk)."""
    path = _feed_path()
    if not path:
        return
    try:
        # One call is one compiler/serving attempt.  This identity is never
        # derived from query_id: chat historically stored a hash of the text
        # there, so two real turns with the same prompt share that value.
        attempt_id = uuid.uuid4().hex
        all_diagnostics = list(diagnostics or [])
        attempt_diagnostics = len(all_diagnostics)
        normalized_source = str(source_kind or "unknown").strip().lower()
        if not normalized_source:
            normalized_source = "unknown"
        events = []
        for d in all_diagnostics[:_MAX_EVENTS_PER_COMPILE]:
            op_name = None
            if d.op_index is not None and isinstance(ops, list) and d.op_index < len(ops):
                raw_op = ops[d.op_index]
                if isinstance(raw_op, dict):
                    op_name = raw_op.get("op")
            action = _ACTION_BY_OP.get(op_name) or (op_name if isinstance(op_name, str) else None)
            kind_raw = str(d.got) if (d.field_name or "").endswith("kind") and d.got is not None else None
            event = {
                "v": 1,
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "source": "kir",
                "reject_code": _REJECT_BY_DIAG.get(d.code, _FALLBACK_REJECT),
                # The refusal's identity. `reject_code` remains the
                # contractual enum, while `diag_code` names WHAT exactly
                # failed: without it, a correct refusal over ambiguity is
                # indistinguishable from an author's error.
                "diag_code": d.code,
                # 🔴 THE CROSS-CHECK KEY WITH THE JOURNAL, WITHOUT WHICH A
                # PANIC RECORD IS INCOMPLETE (26.08.2026). `KIR-P000`
                # deliberately carries neither the exception text nor the
                # stack: they may contain the source IR, model names,
                # paths, and secrets. All of that lives in the system
                # journal under administrator privileges, and the only way
                # to connect the corpus record to that picture is via
                # `incident_id`. Without it the corpus says "there was a
                # panic" and gives no way to know which one — that is, it
                # answers "how many" but not "what to fix".
                #
                # The field is ADDITIVE (like `diag_code` and `candidates`
                # next to it): diagnostics without an incident simply lack
                # it, old events stay readable, contract v1 is not
                # extended.
                **({"incident_id": d.incident_id}
                   if getattr(d, "incident_id", None) else {}),
                "op_requested": action,
                "kind_requested": kind_raw,        # RAW, no normalization (contract)
                # THE ADDRESS OF THE REFUSAL, NOT JUST ITS NAME.
                # `op_requested` is taken from `op_index` and names the
                # operation's NAME; in a program of twenty walls, this is
                # the address of all twenty at once. `Diagnostic`, however,
                # CARRIES `op_id` — the very identifier `op_outcomes` and
                # `violations` in the witness corpus use for addressing —
                # and the feed used to discard it, so a refusal event had
                # nothing to link it to either an operation instance or an
                # execution line.
                # Both fields are written ONLY when they exist: an empty
                # key would read as "there was no address", and that is a
                # different fact (see `candidates`).
                **({"op_id": str(d.op_id)[:64]} if d.op_id else {}),
                # `field_name` — WHAT exactly failed inside the operation.
                # Right now it lives only inside the prose of `detail`, and
                # any count of "which parameter gets us refused most often"
                # was a matter of parsing text.
                **({"field_name": str(d.field_name)[:64]} if d.field_name else {}),
                "cell": _cell(action, kind_raw),
                "query_id": query_id or None,
                # Orthogonal identity axes.  Missing caller identity stays
                # explicit None; only the attempt is compiler-owned and can
                # therefore always be minted truthfully here.
                "turn_id": str(turn_id)[:128] if turn_id else None,
                "action_id": str(action_id)[:128] if action_id else None,
                "attempt_id": attempt_id,
                "attempt_diagnostics": attempt_diagnostics,
                "query_fingerprint": (
                    str(query_fingerprint)[:128]
                    if query_fingerprint else None
                ),
                "source_kind": normalized_source[:32],
                "stage": str(stage or "compile")[:64],
                "revit_version": revit_version,
                "detail": (d.message_ru or "")[:300],
            }
            candidates = _candidates(d)
            if candidates:
                # Candidates are proof that the compiler did not choose on
                # the author's behalf but offered options. The absence of
                # the field is also a fact: there were none.
                event["candidates"] = candidates
                # 🔴 HOW MANY THERE ACTUALLY WERE (26.08.2026).
                #
                # There are TWO different trimmers here, and they diverged:
                # the diagnostic carries up to `ground._CANDIDATES_SHOWN`
                # items to the model (12 today, derived by measurement
                # over 1344 observations), while telemetry wrote
                # `_MAX_CANDIDATES = 8` — and SILENTLY, with no count of
                # the remainder.
                #
                # Measured on a live run: a `piping_system_types` pool of
                # 11 systems. The model got ALL 11, the corpus recorded 8.
                # Tomorrow's reader of the corpus will read "the model saw
                # eight" — and that will be untrue about our own product.
                # Our named pattern: a quantity is DECLARED in one place
                # (the diagnostic) and READ in another (telemetry), and
                # nothing forced them to agree.
                #
                # 🔴 FIXED WITH A NUMBER, NOT BY RAISING THE CEILING.
                # Equating the eight with the twelve would mean inflating
                # EVERY line of the corpus just to answer "how many were
                # there", a question worth a single field. Trimming
                # telemetry makes sense: the corpus is read by queries, not
                # by eye, and the full list is not needed there. What was
                # missing was exactly the count.
                total = len(getattr(d, "candidates", None) or ())
                if total > len(candidates):
                    event["candidates_total"] = total
            events.append(event)
        if not events:
            return
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — fail-open by contract
        logger.debug("kir rejection telemetry write failed (fail-open)", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# AUTHORING-SCRIPT REFUSALS — A SEPARATE SINK, AND SEPARATE FOR A REASON
# ─────────────────────────────────────────────────────────────────────────────
#
# 🔴 WHY AT ALL. Measured 20.08.2026: the `kir_rejections.jsonl` corpus —
# 2395 lines, window 16.07 → 19.08 — carries ZERO lines from the sandbox.
# The words `KIR-B004`, `sandbox`, and "sandboxes" occur in it zero times.
# The authoring-refusal path (`serving`, `stage="author_script"`) returned
# a typed receipt and never once called the record. So the question "what
# does the model trip on when it writes python" had no source at all, and
# any conclusion about the import allow-list was a DECISION, not a
# measurement — and it is declared as such right at the constant itself.
#
# 🔴 WHY NOT THE SAME FILE. `reject_code` is a CLOSED contract enum
# (KIR_QUEUE_CONTRACT.md v1), and the `coverage_queue.py` consumer ranks
# COVERAGE GAPS by it. `KIR-B004` would have landed there as
# `VALIDATION_FAILED` — meaning the author tripping over our own
# allow-list would pose as an uncovered Revit operation. This is exactly
# "one word for two troubles", the very thing the whole neighboring block
# was written against. Different phenomena — different sinks.
#
# 🔴 AND THE COUNTER IS NOT FOR SHOW. Telemetry must be fail-open (a
# failure to record must never change the refusal it describes), but a
# silent fail-open makes "the model did not trip" indistinguishable from
# "we did not record it" — pattern 34, bought on 18.08 on a journal bench
# that undercounted THREEFOLD and never complained. So the sink has an
# OBSERVABLE counter of failed writes.

# 🔴 WHERE THE REFUSAL CAME FROM — A THIRD FIELD, WITHOUT WHICH THE CORPUS
# WOULD MIX THE TEST BENCH WITH PROD. Found 20.08.2026 by a neighboring
# wave RIGHT AFTER the sink was set up: the bench calls the very same prod
# function, `_script_refusal_result`, as the live door, so its refusals
# land in the same append-only journal INDISTINGUISHABLY. A future count of
# "what does the model trip on when it writes python" would lie all the
# harder the more the bench is run — and it would lie silently.
#
# THE DEFAULT IS HONEST: empty means UNKNOWN, not "a live turn". Only
# whoever knows the origin can mark it, and this is NOT the place to
# record it: both the bench and prod enter the very same function. So the
# marker is taken from the calling context, not from an argument — an
# argument would have to be threaded through signatures that are not ours,
# and the very first forgotten parameter would bring back
# indistinguishability.
_ORIGIN: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "kir_author_origin", default="")


@contextlib.contextmanager
def author_origin(name: str):
    """Mark the origin of authoring refusals inside a block.

    Called by WHOEVER KNOWS: the bench wraps its own run, the live door
    wraps nothing. The absence of a mark is a separate, HONEST outcome:
    `origin: null` reads as "not reported", and it must not be passed off
    as a live turn.
    """
    token = _ORIGIN.set(str(name)[:32])
    try:
        yield
    finally:
        _ORIGIN.reset(token)


_AUTHOR_ENV = "KIR_AUTHOR_REFUSALS_PATH"
AUTHOR_FEED_SCHEMA = "kir-author-refusals/1"

#: Observable accounting of the sink itself: `written` — lines recorded,
#: `dropped` — a write did NOT happen (an exception), `disabled` — there
#: is no sink at all (the path did not resolve). Three outcomes, not two:
#: "zero refusals" and "the sink is off" are different facts.
AUTHOR_FEED_COUNTS: dict[str, int] = {"written": 0, "dropped": 0, "disabled": 0}


def _author_feed_path() -> Optional[str]:
    """Where to write the author's refusals, or None — "the sink is off".

    Same order as its neighbor: env ⇒ THIS install's data directory ⇒
    None. Outside the source tree, the last step is silence, not an
    attempt to create someone else's directory.
    """
    path = env.get(_AUTHOR_ENV)
    if path:
        return path
    owned = install_data_path("telemetry", "kir_author_refusals.jsonl")
    return str(owned) if owned is not None else None


def record_author_refusal(
    refusal: Any,
    *,
    source_digest: str = "",
    allowed_imports: Any = (),
    turn_id: str = "",
    query_id: str = "",
) -> None:
    """Record ONE authoring-script refusal. Fail-open, but accounted for.

    THE SOURCE IS NEVER WRITTEN — only its signature. The program's text
    belongs to the author, it is already signed in the receipt
    (`author_digest`), and a second copy of it in telemetry would be an
    attack surface with no consumer.

    What is written is what lets you DECIDE: the code, the kind, whose
    fault it is, the NAME of the module or builtin (the whole reason the
    sink was set up), the script's line, and the allow-list of THAT
    PARTICULAR RUN — without it `KIR-B004` cannot be read: the list is
    live and changes with a flag.
    """
    path = _author_feed_path()
    if not path:
        AUTHOR_FEED_COUNTS["disabled"] += 1
        return
    try:
        detail = getattr(refusal, "detail", None)
        detail = detail if isinstance(detail, dict) else {}
        row = {
            "v": AUTHOR_FEED_SCHEMA,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "code": str(getattr(refusal, "code", "") or "")[:32],
            "kind": str(getattr(refusal, "kind", "") or "")[:64],
            "blame": str(getattr(refusal, "blame", "") or "")[:16],
            "line": getattr(refusal, "line", None),
            # THE NAME — the whole reason the sink exists: "import
            # forbidden" without the module's name answers not a single
            # question about the allow-list.
            "module": str(detail.get("module") or "")[:128] or None,
            "name": str(detail.get("name") or "")[:64] or None,
            "allowed_imports": [str(x)[:64] for x in (allowed_imports or ())],
            "source_digest": str(source_digest)[:64] or None,
            "turn_id": str(turn_id)[:128] or None,
            # Empty = UNKNOWN. No reader is entitled to read the absence
            # as "a live turn".
            "origin": _ORIGIN.get() or None,
            "query_id": str(query_id)[:128] or None,
            "detail": str(getattr(refusal, "message_ru", "") or "")[:300],
        }
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        AUTHOR_FEED_COUNTS["written"] += 1
    except Exception:  # noqa: BLE001 — fail-open by contract, BUT ACCOUNTED FOR
        AUTHOR_FEED_COUNTS["dropped"] += 1
        logger.debug("author refusal telemetry write failed (fail-open)",
                     exc_info=True)


# ═════════════════════════════════════════════════════════════════════════════
# THIRD SINK: COURSE CONSUMPTION
# ═════════════════════════════════════════════════════════════════════════════
#
# 🔴 WHY. Measured 22.08.2026: `kir_witness.jsonl` (5372 lines) and
# `kir_programs.jsonl` (488) carry `author_digest` — the SOURCE's
# signature — and not a single field of either corpus answers whether the
# author READ the course. 16 lessons across 42,264 characters, 8 recipes,
# a registry on call: built, shipped, and NEVER ONCE measured by
# consumption. As long as there is no instrument, "does the course work"
# is an opinion.
#
# 🔴 WHY A THIRD SINK, RATHER THAN A FIELD IN SOMEONE ELSE'S LINE. The plan
# for this step said "the same transport, we are not starting a second
# one", and reading the code refuted that — both existing lines are wrong
# ON THE SUBJECT:
#
#   * `witness_feed.record_witness` — a line about LIVE EXECUTION in
#     Revit: `revit_version`, `ops`, `plan_digest`, the four
#     `live_op_rates` buckets. A turn that only ASKED (`course()` and not
#     a single operation) never reaches it at all — and that is exactly
#     the turn where the course is read most often. A line set up there
#     would measure consumption everywhere except where it is consumed.
#   * `record_author_refusal` — a line about a REFUSAL, and it is absent
#     on success.
#
# The argument "different phenomena — different sinks" is recorded twenty
# lines above on its own example (`KIR-B004` in the coverage bucket would
# pose as an uncovered Revit operation). Here it is the same argument, so
# the sink is separate — but the plumbing is shared: the same telemetry
# directory, the same fail-open WITH ACCOUNTING, the same `author_origin`
# origin marker, the same law "the source is never written".
#
# ONE LINE PER ONE AUTHORING RUN, both outcomes. There is one spot for
# it — `serving._authored_input_from_script`, the very place where the
# authorship receipt is built: EVERY turn with `program_py` passes through
# it, and no other.

_COURSE_ENV = "KIR_COURSE_UPTAKE_PATH"
COURSE_FEED_SCHEMA = "kir-course-uptake/1"

#: The same triple accounting as its neighbor: "zero reads" and "the sink
#: is off" are different facts, and a silent fail-open makes them
#: indistinguishable (pattern 34).
COURSE_FEED_COUNTS: dict[str, int] = {"written": 0, "dropped": 0, "disabled": 0}

#: The ceiling on the ledger within the line. The ledger itself is already
#: trimmed inside the sandbox (`course.MAX_READS`); this is the second end
#: of the same limit — for the case where the line arrives from outside
#: the sandbox.
_MAX_COURSE_READS = 64


def _course_feed_path() -> Optional[str]:
    """Where to write course consumption, or None — "the sink is off".

    Same order as both neighbors: env ⇒ THIS install's data directory ⇒
    None. Outside the source tree, the last step is silence, not a write
    into someone else's install.
    """
    path = env.get(_COURSE_ENV)
    if path:
        return path
    owned = install_data_path("telemetry", "kir_course_uptake.jsonl")
    return str(owned) if owned is not None else None


def record_course_uptake(
    result: Any,
    *,
    source_digest: str = "",
    turn_id: str = "",
    query_id: str = "",
) -> None:
    """Record ONE authoring run: what the course gave the author.
    Fail-open, accounted for.

    ZERO IS ALSO WRITTEN. A turn with not a single access to the course is
    exactly the principal measured number ("the course is shipped and not
    read"), and skipping such lines would mean computing the read share
    over readers alone.

    THERE IS NO SOURCE HERE, same as its neighbor: it is signed by
    `author_digest`, and a second copy of it in telemetry would be an
    attack surface with no consumer. There is no lesson text either — all
    the line needs from it is its LENGTH.
    """
    path = _course_feed_path()
    if not path:
        COURSE_FEED_COUNTS["disabled"] += 1
        return
    try:
        raw = getattr(result, "course_reads", None) or []
        reads = [r for r in raw if isinstance(r, dict)][:_MAX_COURSE_READS]
        refusal = getattr(result, "refusal", None)
        row = {
            "v": COURSE_FEED_SCHEMA,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source_digest": (str(source_digest)
                              or str(getattr(result, "author_digest", "") or ""))[:64] or None,
            "ok": bool(getattr(result, "ok", False)),
            # The refusal code sits next to the ledger ON PURPOSE:
            # `KIR-B013` (reconnaissance) is a turn that asked and did not
            # build, and without the code such a line is indistinguishable
            # from a failed build.
            "code": str(getattr(refusal, "code", "") or "")[:32] or None,
            "op_count": len(getattr(result, "ops", None) or []),
            "stdout_chars": len(str(getattr(result, "stdout", "") or "")),
            "calls": len(reads),
            "chars": sum(int(r.get("chars") or 0) for r in reads),
            "reads": [{k: v for k, v in r.items()
                       if k in ("call", "topic", "chars", "dropped")}
                      for r in reads],
            "turn_id": str(turn_id)[:128] or None,
            "query_id": str(query_id)[:128] or None,
            # Empty = UNKNOWN. No reader is entitled to read the absence
            # as "a live turn" — the bench and prod enter the same
            # function.
            "origin": _ORIGIN.get() or None,
        }
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        COURSE_FEED_COUNTS["written"] += 1
    except Exception:  # noqa: BLE001 — fail-open by contract, BUT ACCOUNTED FOR
        COURSE_FEED_COUNTS["dropped"] += 1
        logger.debug("course uptake telemetry write failed (fail-open)",
                     exc_info=True)
