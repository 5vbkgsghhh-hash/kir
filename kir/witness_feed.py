"""KIR witness telemetry — empirical Revit semantics from prod (wave A6).

Every LIVE execution of a KIR program already returns a witness
readback — but it used to die inside the tool's response. This module
persists triples (op skeleton, version, witness/violations) into an
append-only JSONL: a corpus of Revit's real behavior accumulates by
version (actual tolerances, API quirks, failure rates) — every prod run
becomes a test. The consumer (tolerance priors) is a separate wave.

The coverage_feed discipline: fail-open entirely (a write failure never
breaks a turn), no raw coordinates — only a skeleton hash of the
parameters (numbers → "#", as in the compile_cache normalizer, but over
JSON), a cap on record size.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from kir import env  # noqa: E402  (a dependency-free submodule — creates no import cycle)
import threading
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from kir.install_paths import install_data_path

try:  # Linux production; tests keep a portable no-op fallback.
    import fcntl
except ImportError:  # pragma: no cover - Windows development only
    fcntl = None

logger = logging.getLogger(__name__)

_ENV = "KIR_WITNESS_PATH"
# §18.5: a missing path = the feed is OFF, not a write into someone
# else's filesystem.
_DEFAULT = None
# The fallback is kept because KIR_WITNESS_PATH is not in the prod .env,
# and the .env must not be touched: without it, the witness corpus on
# prod would silently go quiet. Previously the signal was
# isdir("/opt/kukai-rebuild1") — that is, "the path exists ON THE
# MACHINE", not "we were launched from it"; measured 02.08 showed that a
# process from a worktree resolved into the PROD corpus. The address now
# belongs to the install the module was imported from (install_paths —
# one authority for four former conventions).


def _feed_path():
    path = env.get(_ENV)
    if path:
        return path
    if path is None:
        owned = install_data_path("telemetry", "kir_witness.jsonl")
        if owned is not None:
            return str(owned)
    return _DEFAULT
# The record ceiling must cover the LARGEST executable program, or the
# corpus only measures a fraction of it. Measured 31.07 with a live
# loop on the Snowdon sample: 26 chunks, 6344 executions, 833 made it
# into the journal — a third. Because of this, `create_duct` did not
# gather enough witnesses (34 recorded versus 181 executed) and did not
# cross 95%, WITHOUT EVER REFUSING ONCE. The compiler performed
# flawlessly; it was the gauge that fell short — the third time in one
# day.
#
# The bar is not set by eye: `MAX_VALIDATED_OPS` is the program ceiling
# after macro expansion, so by construction nothing executable is ever
# larger. The import is deferred inward so telemetry does not drag the
# compiler in at load time.
#
# The cost is measured, not estimated: a row for 250 operations weighs
# ~25 KB, a whole loop ~640 KB at the corpus's current megabyte scale.
# Skeleton hashes and "numbers → #" are preserved — coordinates still
# never leave the model.
def _max_ops_per_record() -> int:
    try:
        from kir.compiler import MAX_VALIDATED_OPS
        return int(MAX_VALIDATED_OPS)
    except Exception:  # noqa: BLE001 — telemetry has no right to crash
        return 320


_MAX_OPS_PER_RECORD = _max_ops_per_record()

#: How many NON-op DICTIONARY keys of the payload land in one record.
#: The receipt is flat: alongside the per-row readbacks sit
#: program-level keys (`results`, `created_ids`,
#: `postcondition_violations` — three of them today).
#:
#: 🔴 THE LIMIT WAS INTRODUCED ON 30.08.2026 TOGETHER WITH F-068 AND
#: BECAUSE OF IT. Before that fix, record size was bounded by a SINGLE
#: op ceiling, which cut the whole payload — and in doing so also
#: crowded out real ops with program-level keys. By separating one's
#: own keys from foreign ones, I removed that bound, and a payload with
#: a hundred non-op dictionary keys would inflate `op_outcomes` without
#: limit. The limit is generous: it guards against a payload anomaly,
#: it does not cut normal operation.
_MAX_FOREIGN_KEYS_PER_RECORD = 64
_MAX_VIOLATIONS = 10
#: The ceiling on ONE line of free text in a record. Not new: the
#: corpus has stored exactly this much for every violation since the
#: feed was introduced (`violations` = `str(v)[:200]`), and a refusal's
#: identity travels by the same measure — introducing a second ceiling
#: for text of the same nature would mean having two size disciplines
#: instead of one.
_MAX_TEXT = 200

#: The budget of SCALAR readback facts that reach ONE op.
#:
#: The number is ASSIGNED, not derived, and it is assigned by
#: measurement: an emission census on 13.08.2026 found 264 distinct
#: receipt keys across 148 files, while the widest single readback
#: (`create_curtain_grid_line`) puts down 11. Sixteen covers every
#: existing op with margin and keeps the row from growing on a program
#: of 300 ops. Trimming is VISIBLE (`__dropped`), not silent.
_MAX_FACTS_PER_OP = 16
#: The ceiling on a fact's string VALUE. A longer value is NOT
#: truncated — it is dropped with a counter: a truncated string reads
#: as complete and therefore lies, and the canon has already paid for a
#: ceiling that cut one half of a field while the other half kept being
#: appended to it.
_MAX_FACT_TEXT = 80
#: The three keys that DECIDE the `op_outcomes` label. The list is
#: COMPLETE BY CONSTRUCTION: its membership is taken from the very
#: expression that computes the label (see `record_witness`), so a
#: fourth key there will require a fix here too.
#:
#: THE CONDITION FOR REVISITING THIS is about TIMING, not location.
#: Completeness rests on the label being decided by the PRESENCE of a
#: key. It expires once the label starts depending on a VALUE: at that
#: point the presence of the key stops being what decides it, and
#: excluding it from the facts BY NAME becomes wrong — the fact will
#: have to be excluded by the same predicate that computes the label,
#: or one value will again travel by two routes.
_LABEL_KEYS = frozenset({"id", "deleted_id", "refused"})


def outcome_label(row: Mapping[str, Any]) -> str:
    """The outcome label of one result row: `refused` / `created` / `other`.

    THE ONLY place where this question is decided. Previously the
    decision sat as an expression inside a loop, and the cross-checking
    test reproduced it as a substring of the source — that is, the
    answer lived in two places, and they drifted apart.

    🔴 THE `id`/`deleted_id` PAIR WAS HANDWRITTEN AND LOST FOUR CREATING
    OPS (measured 15.08.2026). The identity field for
    `create_pipe_system`, `create_room_separator`, `route_duct_system`,
    `route_pipe_system` is `segment_ids`, and all four got `other`. The
    label is read by `tools/live_op_rates.py`, meaning the instrument
    was publishing rates over a corpus where a creating op was not
    counted as having created. In the live corpus, there were **28 out
    of 1913** such turns.

    Now the creating fields are taken FROM THE REGISTRY
    (`address.created_identity_fields` — today `id` and `segment_ids`).
    Two adjacent decisions are stated, not implied:

    * `deleted_id` stays a separate term: a deletion has an identity,
      has nothing created, and the label `created` here means "the op
      brought an identity". This meaning must not be changed
      retroactively — the corpus is read across its whole history;
    * `moved_ids` was DELIBERATELY not added: the fix leaves no new
      trace, and `move_elements` stays `other`, as it was. This is a
      decision, not an oversight.
    """

    from kir.address import created_identity_fields

    if "refused" in row:
        return "refused"
    if any(field in row for field in created_identity_fields()):
        return "created"
    return "created" if "deleted_id" in row else "other"

_WRITE_LOCK = threading.Lock()
_ZERO_CHECKSUM = "0" * 64


class WitnessChainError(ValueError):
    """The v2 witness telemetry checksum chain is malformed or modified."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _row_checksum(previous: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        previous.encode("ascii") + b"\0" + _canonical(dict(body))
    ).hexdigest()


def _acceptance_summary(value: Any) -> dict[str, Any] | None:
    """Index immutable evidence without copying model scope names."""

    if not isinstance(value, Mapping):
        return None
    summary = {}
    for key in (
        "schema_version", "state", "reason", "run_id", "evidence_digest",
        "registration_digest", "expectation_digest",
        "mutation_expectation_digest", "plan_digest", "ground_digest",
        "revit_version",
        "ground_context_digest", "ground_context_execution_bound",
        "ground_context_authoritative",
        "ground_selector_resolution_replayed",
        "ground_derived_artifacts_verified",
        "execution_artifact_binding_digest",
        "journal_checksum", "journal_finalized",
    ):
        item = value.get(key)
        if isinstance(item, str):
            summary[key] = item[:128]
        elif key in (
                "journal_finalized", "ground_context_execution_bound",
                "ground_context_authoritative",
                "ground_selector_resolution_replayed",
                "ground_derived_artifacts_verified") and isinstance(item, bool):
            summary[key] = item
    registration = value.get("registration")
    if isinstance(registration, Mapping):
        for key in ("run_id", "plan_digest", "ground_digest",
                    "expectation_digest"):
            item = registration.get(key)
            if isinstance(item, str):
                summary.setdefault(key, item[:128])
    journal = value.get("journal")
    if isinstance(journal, Mapping):
        summary["journal"] = {
            key: journal[key]
            for key in ("durable", "run_id", "sequence", "checksum")
            if key in journal and isinstance(
                journal[key], (str, int, bool))
        }
    return summary or None


def _readback_facts(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The scalar FACTS of one readback: a count, a boolean, an enum, a VALUE.

    WHY. Before 13.08.2026 the whole readback dict collapsed here into
    one of three label strings, and in a corpus of 1,331 rows there was
    NOT ONE measurement about what was built — only six numbers of the
    record's own bookkeeping. Of 264 receipt keys, 3 made it through,
    and even those only as a fact of presence. So every one of our
    claims that "a live run will answer with a NUMBER" could not come
    true on any run: there was no route. Measured by a channel census,
    not assumed.

    THE RULE AT THE POINT OF LOSS WAS CORRECT — what was broken was its
    EXECUTION. The comment said "only NON-geometric facts — the
    coordinates themselves stay in the model", and that is correct: the
    model is the authority on geometry, a second copy of it in the
    ledger would be a second truth. But `mullions_on_line` is a COUNT,
    `line_locked` is a BOOLEAN, `default_panel_state` is an ENUM — none
    of them a coordinate, yet "not coordinates" was executed as
    "nothing".

    THE KIND OF THIS LIST: **COMPLETE BY CONSTRUCTION.** The decision is
    made by the value's TYPE, not by the key's name, so a key introduced
    tomorrow falls under the rule on its own and no list needs to be
    maintained here. A container (list, dict) is NEVER recorded — sets
    of points, outlines, curves are exactly the geometry the rule was
    written for. This same rule automatically separates the pair that
    reveals the intent: `position_mm` is an array, a coordinate, it does
    not travel; `position_delta_mm` is a scalar, a DISCREPANCY, it does
    travel.

    TRIMMING IS VISIBLE. A dark channel replaced by a lying one is worse
    than a dark one, so what is dropped is counted by kind in
    `__dropped` and never stays silent: ``geometry`` — a container,
    dropped by the rule, this is not a defect; ``over_budget`` — a
    string value longer than the ceiling (dropped whole, NOT
    truncated); ``over_count`` — more fields than the budget.

    Returns None when there is nothing to record — an empty dict in the
    row would be indistinguishable from "there were no facts", and
    these are different things.

    A CONDITION FOR REVISITING THIS is named here so the rule does not
    live forever without grounds. A narrowing without a reason looks
    like an OVERSIGHT, and the next reader "fixes" it out of habit.

    The rule will stop being correct once there appears a **measured
    value that IS a container by its nature** — a distribution, a
    min/max pair, a vector of per-segment residuals. It is not a
    coordinate, there is no reason to keep it out of the ledger, but the
    current type predicate will drop it as geometry.

    **The signal is measurable, not conjectural:** a nonzero
    `__dropped.geometry` on an op whose receipt carries NOT ONE array of
    coordinates. Then it is the list of dropped KINDS that needs
    extending, not the type predicate itself that needs softening:
    softening it would bring a second copy of geometry back into the
    ledger, the very thing the rule was written to forbid.
    """
    facts: dict[str, Any] = {}
    dropped: dict[str, int] = {}

    def _drop(kind: str) -> None:
        dropped[kind] = dropped.get(kind, 0) + 1

    for key, value in row.items():
        if not isinstance(key, str) or key.startswith("_"):
            continue
        if key in _LABEL_KEYS:
            # NOT dropped, and therefore not counted: these three
            # already made it through — via the neighboring
            # `op_outcomes` field, whose label they decide. Recording
            # them here too would mean setting up a second truth about
            # one fact, exactly the defect the rule is written against.
            # The `test_refusal_identity` ratchet caught this on a green
            # row made of nothing but `id` — "what is absent stays
            # absent".
            continue
        if value is None:
            continue                       # nothing was measured — not a fact
        if len(facts) >= _MAX_FACTS_PER_OP:
            _drop("over_count")
            continue
        # bool BEFORE int: in Python bool inherits from int, and the
        # reverse order would record the verdict as a one.
        if isinstance(value, bool):
            facts[key[:64]] = value
        elif isinstance(value, (int, float)):
            facts[key[:64]] = value
        elif isinstance(value, str):
            if len(value) > _MAX_FACT_TEXT:
                _drop("over_budget")
            else:
                facts[key[:64]] = value
        else:
            _drop("geometry")              # list/dict — the model is the authority
    if dropped:
        facts["__dropped"] = dropped
    return facts or None


def _ground_context_summary(value: Any) -> dict[str, Any] | None:
    """Keep proof digests/flags, never the model catalogue or path names."""

    try:
        from kir.midend import GroundingContext
        if isinstance(value, GroundingContext):
            row = value.to_evidence_dict()
        elif isinstance(value, Mapping):
            row = dict(value)
        else:
            return None
    except Exception:  # noqa: BLE001 — telemetry remains fail-open
        return None
    summary: dict[str, Any] = {}
    for key in (
        "schema", "context_digest", "snapshot_digest", "document_digest",
        "revision_digest", "profile_digest", "source",
        "trusted_source", "profile_authoritative", "identity_bound",
        "revision_bound", "execution_bound", "authoritative",
    ):
        item = row.get(key)
        if isinstance(item, str):
            summary[key] = item[:128]
        elif isinstance(item, bool):
            summary[key] = item
    return summary or None


def _last_chain_state(handle) -> tuple[str, bool]:
    """Return (previous checksum, reset marker) under the file lock."""

    handle.seek(0)
    last = None
    for line in handle:
        if line.strip():
            last = line
    if last is None:
        return _ZERO_CHECKSUM, False
    try:
        row = json.loads(last)
    except json.JSONDecodeError as exc:
        raise WitnessChainError("witness feed has an invalid JSON tail") from exc
    if not isinstance(row, dict) or row.get("v") != 2:
        # A v1 prefix remains readable, but v2 explicitly names the new chain
        # segment instead of pretending the legacy row had a checksum.
        return _ZERO_CHECKSUM, True
    checksum = row.get("checksum")
    if (not isinstance(checksum, str) or len(checksum) != 64
            or any(char not in "0123456789abcdef" for char in checksum)):
        raise WitnessChainError("witness feed tail checksum is malformed")
    body = {key: value for key, value in row.items() if key != "checksum"}
    previous = body.get("prev_checksum")
    if not isinstance(previous, str) or _row_checksum(previous, body) != checksum:
        raise WitnessChainError("witness feed tail checksum is invalid")
    return checksum, False


def verify_witness_chain(path: str) -> int:
    """Verify every v2 segment in a mixed legacy/v2 witness log."""

    expected = _ZERO_CHECKSUM
    after_legacy = False
    verified = 0
    with open(path, "r", encoding="utf-8") as source:
        for index, line in enumerate(source):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise WitnessChainError(
                    f"invalid witness JSON at row {index}") from exc
            if not isinstance(row, dict) or row.get("v") != 2:
                expected = _ZERO_CHECKSUM
                after_legacy = True
                continue
            checksum = row.get("checksum")
            body = {key: value for key, value in row.items()
                    if key != "checksum"}
            previous = body.get("prev_checksum")
            reset = body.get("chain_reset") is True
            if after_legacy and not reset:
                raise WitnessChainError(
                    f"v2 row {index} failed to name its legacy chain reset")
            if not after_legacy and reset:
                raise WitnessChainError(
                    f"v2 row {index} contains an unexplained chain reset")
            if previous != expected:
                raise WitnessChainError(
                    f"witness checksum chain broke at row {index}")
            if (not isinstance(checksum, str)
                    or _row_checksum(expected, body) != checksum):
                raise WitnessChainError(
                    f"witness row {index} was modified")
            expected = checksum
            after_legacy = False
            verified += 1
    return verified


def _skeleton(value: Any) -> Any:
    """Numeric leaves → "#" (coordinates/sizes never leave the model),
    structure/selector strings are preserved — that is enough to key
    the op's "shape" behavior without leaking the client's geometry."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return "#"
    if isinstance(value, dict):
        return {k: _skeleton(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_skeleton(v) for v in value]
    return value


def _op_id(op: Any) -> Optional[str]:
    """The operation identifier — the thing `op_outcomes` and
    `violations` are addressed by.

    31.07: without it, the corpus was UNABLE to name the operation that
    failed. The row knew that the program had `create_wall` and
    `create_door`, and separately knew that a violation belonged to
    `PD` — but there was nothing to connect the two, and the failure had
    to be blamed on both. That is how `create_wall` came out at 64.2%
    while the wall was actually built.

    Adds no leak: the same identifiers already sit in `op_outcomes` and
    verbatim inside `violations`. The cap is the same as for
    `op_outcomes` keys."""
    if not isinstance(op, dict):
        return None
    raw = op.get("id")
    return str(raw)[:64] if raw is not None else None


def op_skeleton_hash(op: Any) -> str:
    """A stable skeleton hash of one op (without the volatile id).

    The id is deliberately EXCLUDED: the skeleton must survive an
    operation being renamed. That is why the identifier is written NEXT
    TO the hash, not inside it."""
    if not isinstance(op, dict):
        return "malformed"
    body = {k: v for k, v in op.items() if k != "id"}
    blob = json.dumps(_skeleton(body), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _text(value: Any) -> Optional[str]:
    """One line of free text for the corpus, or None — "nothing to write".

    An empty string is NOT written: a field that is present and empty
    would read as "there was a cause and it was empty", and that is a
    third fact nobody reported.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text[:_MAX_TEXT] if text else None


#: The values of `refusal_cause` — WHERE in this row the cause of
#: redness lives.
#:
#: The field is written ONLY on a non-green row: a success has no
#: cause, and "the absence of a cause" is not a value, it is an
#: absence. A green row must stay byte-for-byte the same (the law
#: "absent stays absent"), so there is no "none" variant here.
_CAUSE_DIAGNOSTIC = "diagnostic"    # the cause is named by a code: `diag_code` and its neighbors
_CAUSE_VIOLATIONS = "violations"    # the cause is named by postcondition violations
_CAUSE_ACCEPTANCE = "acceptance"    # the commit went through; acceptance is what made it red
_CAUSE_UNKNOWN = "unknown"          # NAMED NOT-KNOWING, see the block below


def record_witness(*, program: Any, family: str, revit_version: str,
                   ok: bool, witness: Optional[dict], duration_ms: float,
                   diag_code: Optional[str] = None,
                   diag_op_id: Optional[str] = None,
                   diag_field: Optional[str] = None,
                   diag_message: Optional[str] = None,
                   diag_detail: Optional[str] = None,
                   violations: Optional[list] = None,
                   result_payload: Optional[dict] = None,
                   outcome: Optional[dict] = None,
                   acceptance_evidence: Optional[Mapping[str, Any]] = None,
                   ground_context: Any = None,
                   author_digest: Optional[str] = None,
                   env_digest: Optional[str] = None,
                   txn_isolation: Optional[str] = None,
                   certificate: Optional[Mapping[str, Any]] = None,
                   query_id: str = "",
                   turn_id: str = "",
                   action_id: str = "",
                   doc_key: str = "",
                   ) -> None:
    """Record one LIVE execution. Never raises (fail-open)."""
    path = _feed_path()
    if not path:
        return
    try:
        from kir.midend import PlannedProgram
        planned = program if isinstance(program, PlannedProgram) else None
        raw_ops = (planned.to_ops() if planned is not None else
                   (program.get("ops") if isinstance(program, dict) else None) or [])
        ops = [{"op": o.get("op"), "id": _op_id(o), "skel": op_skeleton_hash(o)}
               for o in raw_ops[:_MAX_OPS_PER_RECORD] if isinstance(o, dict)]
        record: dict[str, Any] = {
            "v": 2,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source": "kir-witness",
            "revit_version": revit_version,
            "family": family,
            "ok": ok,
            "duration_ms": round(float(duration_ms), 1),
            "ops": ops,
        }
        # 🔴 TURN IDENTITY — WITHOUT IT TWO CORPORA DO NOT RECONCILE BY
        # ANYTHING (26.08.2026, named by a neighboring session on the
        # marathon, checked by a census: 3878 witness rows, `query_id`
        # in NOT ONE of them).
        #
        # The neighboring refusal feed (`coverage_feed.record_rejections`)
        # has carried `query_id`/`turn_id`/`action_id` from the very
        # start — and they already sit in the scope of
        # `_handle_revit_ir_inner`, from which BOTH feeds are called.
        # That is, the value was right there, one argument away, and it
        # never reached the witness.
        #
        # The cost of the silence is measurable: the witness corpus
        # ("what got built") and the corpus of the model's reasoning
        # ("why it decided that") sit side by side and SHARE NO COMMON
        # KEY. The question "is this refusal and this line of reasoning
        # the same event?" is today decided by eyeballing timestamps,
        # i.e. by guessing. The row has `plan_digest`, `author_digest`,
        # `op_outcomes` — all three answer about the PROGRAM and none
        # about the TURN.
        #
        # The field is absent entirely when the identity was not
        # passed: an empty string in the corpus would read as "there
        # was a turn and it did not give its name", and that is a
        # different claim. The same law as for `author_digest` twenty
        # lines below.
        # 🔴 AND THE TASK CARRIER — BY THE SAME LAW AND FOR THE SAME
        # REASON (04.09.2026). The constitution's main metric counts
        # WITHIN ONE TASK; in this tree, the task is the DOCUMENT.
        # Measured: witness rows with `doc_key` — ZERO out of 4268, the
        # field is absent entirely, and that is why the
        # `decision_changes` instrument printed "distinguishable tasks
        # in the feed: 0" and REFUSED to declare a mission outcome. The
        # value sat in the scope of the caller
        # (`serving._turn_journal_document()`) — exactly the same
        # one-argument distance as the turn identity on 26.08.
        #
        # A document, not a device: the owner routinely has two Revits
        # open at once (mandate item 19), and the task is a building,
        # not a machine.
        for _имя, _знач in (("query_id", query_id), ("turn_id", turn_id),
                            ("action_id", action_id), ("doc_key", doc_key)):
            if isinstance(_знач, str) and _знач:
                record[_имя] = _знач[:128]
        if planned is not None:
            # Bind the telemetry row to the exact immutable plan lowered by
            # the compiler. No geometry is copied into the row; op skeletons
            # retain their existing numeric redaction.
            record["plan_schema"] = planned.evidence_schema
            record["plan_digest"] = planned.plan_digest
            record["source_op_count"] = planned.source_op_count
        # THE SIGNATURE OF THE SOURCE THAT PRODUCED THE PROGRAM. Travels
        # next to `plan_digest` and by exactly the same rules:
        # `plan_digest` answers "what was compiled", `author_digest` —
        # "what wrote it". The field is absent entirely when the
        # program was written as operations: an empty string in the
        # corpus would read as "there was a script and it did not sign
        # itself".
        if isinstance(author_digest, str) and author_digest:
            record["author_digest"] = author_digest[:128]
            record["authored_in"] = "python"
        # THE ENVIRONMENT SIGNATURE — the third link in the same chain.
        # `plan_digest` answers "what was compiled", `author_digest` —
        # "what wrote it", `env_digest` — "what it was computed on". The
        # corpus is append-only and outlives library upgrades; without
        # this field, two runs of the same script with different
        # outcomes are indistinguishable from nondeterminism, when the
        # actual cause was a shapely upgrade. The field is absent
        # entirely when the program was written as operations.
        if isinstance(env_digest, str) and env_digest:
            record["env_digest"] = env_digest[:128]
        if len(raw_ops) > _MAX_OPS_PER_RECORD:
            record["ops_truncated"] = len(raw_ops) - _MAX_OPS_PER_RECORD
        if witness is not None:
            record["witness"] = witness
        if isinstance(outcome, dict):
            # The outcome is the closed KIR wire contract, not an inferred
            # restatement of ``ok``.  In particular ``committed`` may coexist
            # with ``ok=false`` when a report-mode witness was violated.
            record["outcome"] = dict(outcome)
        acceptance = _acceptance_summary(acceptance_evidence)
        if acceptance is not None:
            record["acceptance_evidence"] = acceptance
        context = _ground_context_summary(ground_context)
        if context is not None:
            record["ground_context"] = context
        if diag_code is not None:
            record["diag_code"] = diag_code
        # THE OPERATION THAT DIAGNOSTICS ALREADY NAMED.
        #
        # `serving._translate_runtime` puts `op_id` into the diagnostic
        # when the runtime reported it — and telemetry was taking only
        # ONE code from there and dropping the address. The cost is
        # measured on the corpus, 09.08: 181 live red rows carry
        # X003/X999 — codes that by construction do not name the
        # culprit (the distinguishing feature lives in `detail`, and
        # `detail` is not written to the corpus). All of them end up
        # "unattributable", with nothing to recover them by. The field
        # is here so future rows do not have this hole; it adds no leak
        # — the same identifiers already sit in `op_outcomes` and
        # verbatim inside `violations`.
        if diag_op_id is not None:
            record["diag_op_id"] = str(diag_op_id)[:64]
        # ─── THE FULL IDENTITY OF A REFUSAL, NOT JUST ITS CODE ──────────────
        #
        # WHAT WAS MEASURED (09.08.2026, by enumerating ALL keys of ALL
        # 1306 rows of `kir_witness.jsonl`): not one row carries a field
        # with the refusal's message — none at all. A consequence, also
        # measured: of 204 red rows, 165 are unattributable BY
        # CONSTRUCTION (79 X999, 41 unconfirmed, 38 X003, 7 unnamed
        # without an id). For X003 and X999 the distinguishing feature
        # lives EXACTLY in `detail`, and telemetry was dropping
        # `detail` — so a whole class of investigation stayed at
        # reading text next to the corpus instead of querying the
        # corpus. That is exactly how "compiler 5 / Revit 11" was born
        # on 04.08 from 12 `create_door` refusals: not a measurement,
        # but a retelling.
        #
        # WHAT IS RECORDED HERE — only what diagnostics ALREADY carries
        # (`Diagnostic`: code / op_id / field_name / message_ru, plus
        # `detail` for a runtime translation). Not a single new fact:
        # the list is closed HERE, not at the caller, so that "record
        # this too while we're at it" cannot slip in in passing.
        #
        # WHAT WAS DECIDED ABOUT PRIVACY. The corpus is appended to
        # forever and lives on prod, so the question is not "is it
        # allowed" but "exactly what".
        #   * `diag_message` — OUR text (`message_ru`), a closed set of
        #     compiler strings; it carries no model data by
        #     construction;
        #   * `diag_detail` — the words of the RUNTIME ITSELF, and that
        #     is where a family or level name can appear (a refusal for
        #     an unturnable leaf names `FamilySymbol.Family.Name`). We
        #     write it anyway, and here is why this is not a widening
        #     of the perimeter: the texts of `violations` — of the same
        #     nature and from the same model — have been stored
        #     verbatim by the corpus since day one, the file opens at
        #     0600 on EVERY write and belongs to the install
        #     (`install_paths`), and without `detail`, X999 stays
        #     causeless forever. Geometry still never leaves the model:
        #     numbers in the skeletons are "#", there were no
        #     coordinates here and there are none now.
        #   * the ceiling is the shared `_MAX_TEXT` for violations, not
        #     a new one.
        for key, value in (("diag_field", diag_field),
                           ("diag_message", diag_message),
                           ("diag_detail", diag_detail)):
            text = _text(value)
            if text is not None:
                record[key] = text
                # THE THIRD CARRIER OF THE LAW "TRUNCATION MUST NAME
                # ITSELF." The first two (`ops_truncated`,
                # `violations_truncated`) are named a few lines below
                # and above; this one stayed silent. Paid for on 24.08:
                # a KIR-A007 text 235 characters long was cut exactly
                # in the middle — the corpus kept "do NOT retry it",
                # while what fell off was "(retry: forbidden), already
                # built in the model", that is, EXACTLY what this text
                # was written for. A reader of the corpus saw a stub
                # and had no way to know a second half had existed.
                full = str(value).strip()
                if len(full) > len(text):
                    record[key + "_truncated"] = len(full) - len(text)
        # ═══ TRANSLATION CERTIFICATE: THE SECOND CASE OF ONE FORM IN A
        # SINGLE DAY ═══
        #
        # 🔴 24.08.2026. The value IS COMPUTED, reaches the MODEL
        # (`out_result["certificate"]`) and DOES NOT LAND IN THE
        # CORPUS. Measured live: `KUKAI_IR_TRANSLATION_CERT=record` has
        # been set since 24.08, the model's response carries
        # `{"mode":"record","status":"proven","refused":false,...}` —
        # yet in a corpus of 3732 rows, the number of records with a
        # certificate is EXACTLY ZERO.
        #
        # The cost is precisely this: the `record -> refuse`
        # translation plan rested on the promise that "in a day, the
        # receipts will show a number for how many live records it
        # would have refused". That number would NEVER have existed —
        # an observation mode without a journal is indistinguishable
        # from being off, and the decision would be made by nerve, not
        # by measurement. Exactly the same kind as the one closed today
        # for acceptance diagnostics; the second instance in one day,
        # hence a field, not a one-off fix.
        #
        # PRIVACY. The list of keys is closed HERE, as with `diag_*`:
        # mode, Revit version, the NUMBER of ops, status, duration,
        # refusal. None of them carries model data — names, geometry
        # and texts do not occur here by construction.
        if isinstance(certificate, Mapping):
            keep = ("mode", "status", "refused", "ops", "duration_ms",
                    "revit_version")
            row = {k: certificate[k] for k in keep if k in certificate}
            if row:
                record["certificate"] = row
        if violations:
            record["violations"] = [str(v)[:_MAX_TEXT]
                                    for v in violations[:_MAX_VIOLATIONS]]
            # Truncation must be NAMED. A twenty-beam program with
            # twenty violations left ten of them in the corpus and no
            # trace that more had existed — and it read as "that was
            # all there was".
            if len(violations) > _MAX_VIOLATIONS:
                record["violations_truncated"] = len(violations) - _MAX_VIOLATIONS
        committed = (
            isinstance(outcome, dict)
            and outcome.get("execution") == "committed"
        )
        # ─── AN UNKNOWN CAUSE IS ALSO A RECORD ──────────────────────────────
        #
        # To a reader of the corpus, a red row with no code and no
        # violations looks exactly like a row whose cause simply was
        # not recorded — and there is nothing to tell "the cause was
        # not named" apart from "the field was forgotten". So a
        # non-green row ALWAYS says WHERE its cause lives, and the last
        # of the values names the not-knowing out loud: `unknown` is a
        # claim, not a gap.
        #
        # This does not touch a green row by a single byte: a success
        # has no cause, and its absence must look like an absence.
        # REVIT TRANSACTION ISOLATION IS NOT THE PYTHON SANDBOX.
        #
        # `serving._sandbox_receipt` reads the `isolation` field from
        # the SANDBOX's result (`namespaces`/`filesystem`/`network_probe`).
        # This is a different subject under the same word, and on
        # 13.08.2026 it almost led to the conclusion "isolation is
        # already being recorded". That is why the field here is
        # called `txn_isolation`, and the distinction is written HERE —
        # where the next reader will meet the field, not where we
        # discussed it.
        #
        # WHY IT IS IN THE ROW. `tools/live_op_rates.py` counts four
        # buckets, and one of them is "collateral": someone else's
        # violation rolled back the transaction. **Under `per_op` there
        # is no such thing as collateral, BY CONSTRUCTION.** As long as
        # isolation was absent from the row, the corpus mixed two
        # populations with different semantics for this bucket, with
        # nothing to tell them apart: measured 13.08 —
        # `isolation`/`per_op`/`atomic` occur in the 1331-row corpus
        # EXACTLY 0 times. The field is not for curiosity — it is so
        # the main per-op rate instrument stops mixing two semantics.
        #
        # NOT WRITTEN WHEN THE CALLER DID NOT NAME IT. Absence means
        # "not stated" and applies to all 1331 rows before this fix;
        # defaulting this to `"atomic"` would mean retroactively
        # asserting something about them that nobody measured.
        #
        # THE CONDITION FOR REVISITING THIS. This reading is true
        # exactly as long as there exists even one caller that does not
        # name isolation. The pin `test_every_live_call_site_states_it`
        # walks the AST and requires the field at EVERY
        # `record_witness` call site in `serving.py`; while it is
        # green, the only source of absence is rows older than
        # 13.08.2026. Once no such rows remain in the corpus (a single
        # `grep -c` on `ts`), the field's absence will become
        # indistinguishable from a DEFECT — and at that point the
        # correct move is not "supply a default" but to REFUSE a call
        # that lacks isolation.
        if isinstance(txn_isolation, str) and txn_isolation:
            record["txn_isolation"] = txn_isolation[:32]
        if not ok:
            record["refusal_cause"] = (
                _CAUSE_DIAGNOSTIC if diag_code is not None
                else _CAUSE_VIOLATIONS if violations
                else _CAUSE_ACCEPTANCE if committed
                else _CAUSE_UNKNOWN)
        if (ok or committed) and isinstance(result_payload, dict):
            # Post-commit readbacks per op: only NON-geometric facts (id
            # created/refused) — the coordinates themselves stay in the
            # model.
            per_op = {}
            per_op_facts: dict[str, Any] = {}
            # THE AUTHORITY ON OPS IS THE LIST OF OPS, NOT THE SHAPE OF
            # A VALUE. The receipt is FLAT: program-level keys (`ok`,
            # `created_ids`, `postcondition_violations`, `results`) sit
            # in it mixed together with per-row readbacks keyed by
            # `oid`. Today only readbacks carry a dict value, so "take
            # all dict values" works — but that is a property of the
            # SHAPE, not a check: a `summary: {...}` added nearby would
            # introduce a nonexistent op into the facts, and it would
            # be looked up in the registry. We take identifiers from
            # THE PROGRAM ITSELF, before truncation (`raw_ops`, not
            # `ops`), otherwise a wide program would lose legitimate
            # facts past the record ceiling.
            _known_oids = {_op_id(o) for o in raw_ops if isinstance(o, dict)}
            _known_oids.discard(None)
            # 🔴 FILTER FIRST, THEN THE CEILING (30.08.2026, audit
            # finding F-068). The slice stood BEFORE the check against
            # the op list, so program-level keys with a dict value
            # (`results`, `created_ids`, `postcondition_violations` —
            # three of them today) WERE TAKING UP SLOTS in the slice,
            # and on a program at the legitimate maximum, exactly that
            # many REAL ops silently fell out. The ceiling must bound
            # OPS, not everything indiscriminately.
            #
            # The pseudo-ops STAY IN THE RECORD — the label's
            # continuity is a named property of the corpus,
            # `live_op_rates` reads it across the whole history — but
            # they no longer COMPETE with real ones for slots. The fix
            # changes the ORDER, not the membership.
            _mine = [(k, v) for k, v in result_payload.items()
                     if isinstance(v, dict) and str(k)[:64] in _known_oids]
            _foreign = [(k, v) for k, v in result_payload.items()
                        if isinstance(v, dict) and str(k)[:64] not in _known_oids]
            # 🔴 FOREIGN ONES ARE BOUNDED TOO, AND NOT BY THIS PACKAGE.
            # The form of the finding was taking them WHOLE, and the
            # record lost its upper bound: previously it was held by a
            # single ceiling, and after the split a payload with a
            # hundred non-op dictionary keys would inflate
            # `op_outcomes` without limit. Today there are three such
            # keys, so the limit is generous — it guards against a
            # payload anomaly, it does not cut normal operation.
            for oid, row in (_mine[:_MAX_OPS_PER_RECORD]
                             + _foreign[:_MAX_FOREIGN_KEYS_PER_RECORD]):
                if isinstance(row, dict):
                    key = str(oid)[:64]
                    per_op[key] = outcome_label(row)
                    # The label is NOT bounded by the op list: it has
                    # been written since 2026-07 and its continuity is
                    # a property of the corpus that `live_op_rates`
                    # reads across the whole history. What is bounded
                    # is the FACT, i.e. exactly what is introduced
                    # today.
                    if key in _known_oids:
                        facts = _readback_facts(row)
                        if facts:
                            per_op_facts[key] = facts
            if per_op:
                record["op_outcomes"] = per_op
                # 🔴 TRUNCATION IS COUNTED BY OPS, NOT BY PAYLOAD KEYS
                # (F-068). The previous number included program-level
                # keys and so answered the wrong question: "how many
                # keys past the ceiling" instead of "how many OPS were
                # lost". A number you cannot use is worse than a
                # missing one.
                if len(_mine) > _MAX_OPS_PER_RECORD:
                    record["op_outcomes_truncated"] = (
                        len(_mine) - _MAX_OPS_PER_RECORD)
                    # AND WHICH ONES EXACTLY: the canon forbids silent
                    # truncation — "if the work limits its scope, print
                    # what was dropped". Only HOW MANY was being
                    # printed.
                    record["op_outcomes_truncated_ids"] = [
                        str(k)[:64] for k, _ in _mine[_MAX_OPS_PER_RECORD:]
                    ][:50]
            # A SEPARATE field, not an enrichment of `op_outcomes`: its
            # values are read as strings (`tools/live_op_rates.py:404`
            # compares against "refused"), and changing their type
            # would break the four-bucket instrument. The fix's radius
            # is the import graph, not the file.
            if per_op_facts:
                record["op_facts"] = per_op_facts
        directory = os.path.dirname(path) or "."
        existed = os.path.exists(path)
        os.makedirs(directory, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            # Existing telemetry from older releases may have inherited a
            # broad umask.  It carries result ids and execution metadata, so
            # narrow it on every successful open instead of protecting only
            # new files.
            os.fchmod(descriptor, 0o600)
            handle = os.fdopen(descriptor, "a+", encoding="utf-8")
        except Exception:
            os.close(descriptor)
            raise
        with _WRITE_LOCK, handle as f:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                previous, chain_reset = _last_chain_state(f)
                record["prev_checksum"] = previous
                if chain_reset:
                    record["chain_reset"] = True
                record["checksum"] = _row_checksum(previous, record)
                f.seek(0, os.SEEK_END)
                f.write(_canonical(record).decode("utf-8") + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        if not existed and hasattr(os, "O_DIRECTORY"):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except Exception:  # noqa: BLE001 — fail-open per the telemetry contract
        logger.debug("kir witness telemetry write failed (fail-open)",
                     exc_info=True)


__all__ = [
    "WitnessChainError",
    "op_skeleton_hash",
    "record_witness",
    "verify_witness_chain",
]
