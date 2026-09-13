"""PROGRAM JOURNAL — a session's accumulated list of programs IS the
BUILDING'S SOURCE CODE.

WHY A SEPARATE MODULE, AND NOT "AN IMAGE PIPELINE". An image is one of
the journal's readers, and not even the main one. The journal is
versioned, diffed, replayed, and the verdict on the whole building is
computed from it; a plan sheet is merely one way to read it. That is
why storing programs is primary here, while drawing lives one floor up
(`plan_stream.py`) and can fall over entirely without touching the
record.

WHAT THE INVENTORY FOUND BEFORE BUILDING THIS (03.08). There is NO
durable record of authored programs in the project, though three things
resemble one:

* `data/telemetry/kir_witness.jsonl` (~1226 lines) — a corpus of
  OUTCOMES, not of programs. `witness_feed._skeleton()` replaces every
  numeric leaf with `"#"` BY CONTRACT ("coordinates do not leave the
  model"); the line keeps the op's name, its id, and a skeleton hash. A
  plan cannot be drawn from it and never will be able to: editing out
  the geometry is this file's purpose, not a shortcoming of it;
* `ir/acceptance_journal.py` — a journal of acceptance PREDICATES
  (fsync before write, a checksum chain). Does not store the program's
  body;
* `kukai/design/review.py:record()` — the ONLY place where programs were
  already being accumulated in full. But: a `ContextVar` for ONE turn
  only, in memory only, only for programs that have ALREADY executed and
  passed acceptance. Three differences from what is needed here (turn vs
  session, after the record vs before, outcome vs intent), so the
  journal is built rather than reused. The reverse is also true and
  recorded, so that in a month nobody builds a third one:
  `review.findings()` is a ready-made second reader of this journal, once
  it is moved from turn to session.

HONESTY OF THE SOURCE. What lies here is what the program DECLARED, and
nothing more. Declaration ≠ construction: the journal is filled AFTER
planning and BEFORE the write, meaning it also contains programs that
Revit later rejected. This is not a defect — it is the price of having
the pipeline work in offline runs, where Revit does not come up at all.
The `stage="planned"` mark travels with every record and with every
frame, while `preview.PreviewSource.PROGRAM` independently stamps the
sheet as `Assertion.SELF_REPORTED` ("DECLARED"). Two marks from two
different modules, and neither is derived from the other.

BOUNDARIES. The journal cannot compile, cannot draw, and cannot send:
not one import from `kukai.api` or `kukai.llm`, and none from `kir` —
except the store (below). The guarantee here is about CAPABILITIES,
not about a list of names.

🔴 THE BOUNDARY WAS NARROWED ON 18.08.2026, AND HERE IS HOW. The
previous version said "stdlib only, not one import from `kir` — neither
at module level nor lazily". The rule was broader than its own
rationale: `journal_store` is a pure store, it does not compile, draw,
or send, and from `kir` it takes EXACTLY the path to the install's data
directory (`install_paths.install_data_path`) — the very same single
dependency its package neighbor `live/transfer_journal.py` already has.
Forbidding it would mean setting up a THIRD place that knows where the
data lives — that is, buying the tree a named defect for the letter of
the rule.

DURABILITY. The in-memory store remains the hot path and the main
reader; `journal_store` writes the same events TO DISK, fail-open.
Before 18.08.2026 it did not exist, and this header's promise
("versioned, diffed, replayed") was kept in NONE of the three: the
building lived until eviction and vanished with the process. A store
failure has no right to bring down a turn — so the write returns a bool
and never raises, and `append`/`advance` do not check it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from kir import env  # noqa: E402  (submodule without dependencies — creates no cycles)
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

__all__ = (
    "BUILT_STAGES",
    "DOC_KEY_IDENTITY_SEP",
    "FOREIGN_JOURNAL_REFUSAL",
    "JOURNAL_SCHEMA",
    "STAGES",
    "ProgramRecord",
    "SessionJournal",
    "SessionKey",
    "advance",
    "append",
    "bind_operation_id",
    "doc_key_for",
    "document_identity_of",
    "document_name_of",
    "get",
    "key_for",
    "named_only_key",
    "reconcile_late_commit",
    "remember_sections",
    "reset",
    "restore_note",
    "sessions",
    "stats",
    "was_evicted",
)

JOURNAL_SCHEMA = "kir-journal/2"


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(env.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


#: Ceilings. The journal lives in the memory of a live service, so there
#: is NO SUCH THING as "unlimited": an infinite journal is a leak with a
#: nice name. Overflow evicts the OLDEST programs and NAMES this with a
#: number (`programs_evicted`), which travels to the sheet. Silently
#: shortening the building's history would mean drawing the wrong
#: building and not saying so.
def _max_programs() -> int:
    return _int_env("KIR_JOURNAL_PROGRAMS", 512, low=8, high=20_000)


def _max_ops() -> int:
    return _int_env("KIR_JOURNAL_OPS", 40_000, low=100, high=2_000_000)


def _max_datums() -> int:
    return _int_env("KIR_JOURNAL_DATUMS", 1_024, low=8, high=100_000)


def _max_sessions() -> int:
    return _int_env("KIR_JOURNAL_SESSIONS", 8, low=1, high=256)


#: Datums (`create_level`, `create_grid`) are stored SEPARATELY from
#: programs and are not evicted along with them. The reason is not
#: economy: without `create_level` a floor loses its NAME, and one and
#: the same "Отметка 0.000" splits, after eviction, into two different
#: floors — `$L1` and "Отметка 0.000". A floor's key must remain stable
#: longer than the program that declared it lives.
_DATUM_OPS = ("create_level", "create_grid")

#: WRITE STAGES — a closed list, and it is CLOSED BY KIND, not by
#: convenience.
#:
#: WHY THEY WERE INTRODUCED (16.08.2026, independent audit + re-check by
#: execution). Before this there was one stage — `planned` — and there
#: was NOTHING to advance it with: the field existed, the literal stood
#: in three places, there was no API at all. The consequence was
#: measured: `verdict.judge` built its batch from ALL of the session's
#: records, meaning it could hand down "BUILDING VERDICT: FIT" to a
#: building that does not exist in Revit as a single element. The same
#: day's measurement: through the chat door, over 24 hours, records in
#: Revit — ZERO, while the journal was full.
#:
#: The project's cardinal invariant requires, for `ok:true`, a confirmed
#: write, an independent re-read, and durable evidence. The judge
#: required NONE of the three — not because someone cancelled it, but
#: because there was NOTHING to tell the declared from the built with.
#:
#: THE MAIN LINE is monotonic: there is no going back along it.
_MAIN_STAGES = ("planned", "grounded", "dispatched", "committed", "accepted")
#: SIDE STAGES — terminal, and they are NOT a fully built program. They
#: cannot be merged, for exactly the same reason that `None` and `{}` are
#: different values here:
#:   * `refused_pre_effect` — never reached the model, nothing to change;
#:   * `rolled_back`        — reached it and was rolled back, no elements
#:     remain;
#:   * `running_unknown`    — there is NO evidence. Not "not built", but
#:     "we don't know", and a retry is forbidden
#:     (`transport.execution_unknown`, `retryable=False`). Collapsing it
#:     into "not built" would mean lying toward the side that looks
#:     safe: the write could have gone through;
#:   * `committed_partial` — part of the program is provably standing,
#:     but this record no longer asserts which operations exactly make up
#:     the complete building.
_SIDE_STAGES = (
    "refused_pre_effect",
    "rolled_back",
    "running_unknown",
    # Part of the chunks are provably written, but the whole authored
    # program is not. Such a record forbids a blind retry, but it has
    # NO right to end up in built(): that holds complete programs, not
    # plausible-looking tails.
    "committed_partial",
)
STAGES = _MAIN_STAGES + _SIDE_STAGES
#: Stages at which a program IS COUNTED AS PART OF THE BUILT BUILDING.
#: Deliberately closed narrowly: everything else is a declaration, not
#: a construction.
BUILT_STAGES = ("committed", "accepted")
_RANK = {name: i for i, name in enumerate(_MAIN_STAGES)}

SessionKey = tuple[str, str]

_LATE_COMMIT_OUTCOME = "CommittedVerified"


def _operation_id(value: Any) -> str | None:
    """Return the exact transport identity, without guessing or coercing anything."""

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text != value or len(text) > 128:
        return None
    return text


def _verified_late_commit_digest(
    operation_id: str,
    receipt: Any,
    *,
    identity_verified: bool,
) -> str | None:
    """Check the narrow authority handed over by the transport's owner.

    KIR does not authenticate sockets or signatures. The host does that,
    after which it passes on the exact receipt together with
    ``identity_verified=True``. Even so, the content-addressed operation
    id and the closed set of commit outcomes are re-checked here: a
    truthy object, someone else's receipt, or a partial/unknown outcome
    have no right to advance the building's state.
    """

    if identity_verified is not True or not isinstance(receipt, Mapping):
        return None
    if _operation_id(receipt.get("operation_id")) != operation_id:
        return None
    if receipt.get("outcome") != _LATE_COMMIT_OUTCOME:
        return None
    # ``outcome`` is the name of a transport outcome, not a witness from
    # Revit. In particular, the old Bridge could derive CommittedVerified
    # from an ordinary method return. Only a separate field is allowed to
    # advance the building's truth, one that the trusted host transaction
    # envelope must set, not a generated user payload.
    if receipt.get("transaction_status") != "Committed":
        return None
    try:
        encoded = json.dumps(
            dict(receipt),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def key_for(device_id: Any, doc_key: Any = "") -> SessionKey:
    """The session key — ONE rule for the whole package.

    The rule is trivial, and precisely for that reason it must live in
    one place: the writer (`plan_stream.publish`) and the readers
    (`verdict.judge`) must land on the same record, and two independent
    `(str(device_id or ""), str(doc_key or ""))` would drift apart at the
    very first refinement of the key — and would drift apart SILENTLY:
    the reader would find an empty journal and honestly say nothing.

    🔴 WHAT THIS FUNCTION DOES NOT DECIDE, AND WHERE THAT IS DECIDED.
    Here `doc_key` is an OPAQUE string, and the rule for "what exactly it
    should be" lives one floor up, in `doc_key_for`. The split is
    deliberate: the session key must remain one rule for the package (the
    writer and the readers), while the document's COMPOSITION is known
    only to whoever has the turn's context. Mixing them would mean
    setting up a second carrier for one of the two rules.
    """
    return (str(device_id or ""), str(doc_key or ""))


#: THE SEPARATOR INSIDE `doc_key`: the document's name on the left, its
#: IDENTITY on the right.
#:
#: `\x1f` (ASCII Unit Separator) was not chosen for looks: it is
#: impossible in a Revit document name — `Document.Title` comes from the
#: file name, and the filesystem does not pass control characters
#: through. Any printable separator (`|`, `#`, `::`) is possible in a
#: name, and the same-name collision we are fixing would come back
#: through a forged name.
DOC_KEY_IDENTITY_SEP = "\x1f"

#: THE NAME OF THE REFUSAL WITH WHICH THE JOURNAL ANSWERS A SAME-NAME
#: COLLISION. A refusal, not a restore: see `doc_key_for` — why
#: restoring would be worse than not restoring.
FOREIGN_JOURNAL_REFUSAL = "journal_of_another_document_with_the_same_name"


def doc_key_for(document_name: Any, document_identity: Any = "") -> str:
    """The journal's `doc_key` is the document's IDENTITY, not its NAME.

    🔴 BOUGHT BY THE OWNER'S LIVE REVIT ON 08.09.2026, AND THIS IS THE
    MOST EXPENSIVE CLASS IN THIS TREE. The owner's word: "I opened a new
    Revit, I'm having a conversation, and it somehow remembers about the
    сарай — that was in a different Revit a week ago." The backend log
    on that same turn:

        kir.live.journal: journal: поднято 194 программ со склада для ключа
        (<устройство>, 'Проект1')

    `Проект1` is the default name of EVERY new Revit document. The
    journal key was `(device, NAME)`, so an empty new document inherited
    194 someone-else's programs from a week ago — levels «KIR суд 1942»,
    «Сарай», «Кровля сарая» — and on «сделай куб» the preview drew 98
    elements of SOMEONE ELSE'S building. This is exactly the class that
    already cost the tree the `S1_L1` record: THE NAME IS STABLE, THE
    REFERENT IS DIFFERENT. No "was it done correctly" check works
    against it — they all stay silent when the work was done to THE SAME
    NAME, but not to the same referent.

    THE RULE. When identity exists — `name\\x1fidentity`; when identity
    does not exist — a bare name, i.e. the previous behavior, named "by
    name, without identity". The name deliberately stays FIRST and
    readable: `doc_key` ends up in the log, in the store, and in the
    receipt, and a person must be able to recognize their document in it
    without decoding anything.

    LIMITS, NAMED OUT LOUD — there are three, and each is chosen
    deliberately:

    1. IDENTITY MAY NOT EXIST AT ALL (an old plugin, a chat without
       Revit, a standalone KIR). Then the key is the old one, and the
       same-name collision is NOT fixed — but it also does not pretend
       to be fixed: `document_identity_of()` will return empty, and
       restoring someone else's journal will name itself
       `FOREIGN_JOURNAL_REFUSAL`.
    2. IDENTITY CHANGES ON THE FIRST SAVE. The plugin's identity carrier
       (`ExecutionContextGuard.ComputeDocumentKey`) computes a sha256 of
       `project-information:<UniqueId>` AND `path:<path>`; an unsaved
       document has no path, a saved one does — the hash differs. So
       after "Save As" the previous session's journal of THIS SAME
       document will not be restored. This is chosen deliberately: "not
       restored" is a VISIBLE, named outcome, while "restored the wrong
       one" is silent and unfixable. The price of the error is
       asymmetric, so the rule is asymmetric too.
    3. TWO DOCUMENTS WITH THE SAME `project_uid` (a file copy made by
       OS-level means before the first open) differ only by path. As
       long as a path exists, they are distinct; as long as neither has
       been saved, they are identical. This is NOT covered, and closing
       it is only possible with a field from the plugin
       (`document_instance_key` lives for exactly one opening session, so
       a re-opened building would lose its journal — worse than the
       disease).
    """
    name = str(document_name or "")
    identity = str(document_identity or "").strip()
    if not identity:
        return name
    # A separator inside the identity would make parsing ambiguous — and
    # an ambiguous parse of the key is exactly the wrong-address mistake.
    identity = identity.replace(DOC_KEY_IDENTITY_SEP, "-")
    return f"{name}{DOC_KEY_IDENTITY_SEP}{identity}"


def document_name_of(doc_key: Any) -> str:
    """The human name of the document from `doc_key` — what the owner sees."""
    return str(doc_key or "").split(DOC_KEY_IDENTITY_SEP, 1)[0]


def document_identity_of(doc_key: Any) -> str:
    """The document's identity from `doc_key`; empty means "by name, without it"."""
    parts = str(doc_key or "").split(DOC_KEY_IDENTITY_SEP, 1)
    return parts[1] if len(parts) == 2 else ""


def named_only_key(key: SessionKey) -> SessionKey:
    """The same key as it WAS BEFORE 08.09.2026 — by name alone.

    Needed for exactly one thing: to find records left in the store by
    the previous version (and records of ANY document with the same
    name), in order to NAME them, not to restore them. A separate
    function, not a slice at the call site: the store's compatibility
    rule must live in the same place as the key rule.
    """
    device = str(key[0]) if len(key) > 0 else ""
    doc = str(key[1]) if len(key) > 1 else ""
    return (device, document_name_of(doc))


@dataclass(frozen=True, slots=True)
class ProgramRecord:
    """One authored program, as accepted by the midend.

    `ops` is what `PlannedProgram.to_ops()` returned: macros expanded,
    defaults filled in, references validated. Exactly what goes on
    downward, not what the author typed — otherwise the sheet would show
    one thing while a different thing got built.
    """

    seq: int
    ts: float
    ops: tuple[Mapping[str, Any], ...]
    plan_digest: str = ""
    author_digest: str = ""
    intent: str = ""
    source: str = ""
    #: One authored program can go out as several chunks. Every transport
    #: operation is stored: a scalar would silently lose all chunks but
    #: one, and a late receipt would become unaddressable.
    operation_ids: tuple[str, ...] = ()
    #: The digest of the authenticated late receipt that lifted the
    #: unknown state. Empty on the ordinary synchronous path and for all
    #: legacy records.
    late_receipt_digest: str = ""
    #: The stage mark, from the closed list `STAGES`. A record is BORN
    #: `planned` — the journal is filled before Revit is even contacted —
    #: and moves only through `advance()`, that is, only once the outcome
    #: HAS BECOME known. The default is deliberately the weakest one:
    #: "declared" and "built" have no right to end up being the same
    #: default value.
    stage: str = "planned"
    #: THE RECORD WAS RESTORED FROM DISK, NOT LIVED THROUGH BY THIS
    #: PROCESS. A separate field, not a guess from the stage: a restored
    #: state is NOT EQUAL to a verified one — the current process never
    #: saw this program's witness and cannot confirm it. A reader holding
    #: just ONE record must be able to see this, not derive it from a
    #: census nobody handed them.
    restored_from_disk: bool = False

    @property
    def op_count(self) -> int:
        return len(self.ops)

    @property
    def is_built(self) -> bool:
        """Whether this program counts as part of the BUILT building."""
        return self.stage in BUILT_STAGES


@dataclass(slots=True)
class SessionJournal:
    """Programs of one session in order of appearance.

    The cursor (`indexed_upto`) belongs to the READER, not to the
    journal: the journal only stores and evicts. Thanks to the cursor, a
    lost frame does not lose the program — the reader catches up from
    where it stopped (see `plan_stream`).
    """

    key: SessionKey
    records: list[ProgramRecord] = field(default_factory=list)
    datums: list[Mapping[str, Any]] = field(default_factory=list)
    #: Datum keys already present in `datums` — a datum is declared once,
    #: but can arrive in every program (`create_level` in a chunk's
    #: header).
    _datum_keys: set[str] = field(default_factory=set)
    next_seq: int = 0
    ops_held: int = 0
    programs_evicted: int = 0
    ops_evicted: int = 0
    datums_dropped: int = 0
    last_ts: float = 0.0
    #: The reader's cursor: the seq of the first program not yet read.
    indexed_upto: int = 0
    #: The reader's index: floor mark -> seq of the programs that touched
    #: it.
    level_index: dict[str, list[int]] = field(default_factory=dict)
    #: A summary by FLOOR: how many operations were presented to a floor.
    #: The number is taken from `preview`'s own `census.considered` —
    #: there is deliberately no rule of its own here for "whose operation
    #: is this" (see `plan_stream._slice_for`).
    level_tally: dict[str, int] = field(default_factory=dict)
    #: A summary by OPERATION for the whole session. There is no way to
    #: break it down further by floor as well without setting up a second
    #: instance of the ownership rule — so it is honestly one per
    #: building, not an invented per-floor one.
    op_tally: dict[str, int] = field(default_factory=dict)
    #: TYPE GEOMETRY OF THIS DOCUMENT (the sections wave): level
    #: elevations and type sections, captured by the ground stage from
    #: the LIVE model and already cleaned up
    #: (`open_model.prune_ground_snapshot`). The journal does not
    #: interpret them and knows nothing about them — it STORES them,
    #: because it is the only place where a session outlives a turn, and
    #: a wall's body cannot be built from a single program.
    #:
    #: `None` and `{}` are DIFFERENT facts: "ground did not answer"
    #: versus "it answered, and the types have no sections". The reader
    #: must distinguish them, so here too they are different values.
    sections: dict[str, Any] | None = None

    # -- write ---------------------------------------------------------------
    def append(self, record: ProgramRecord) -> ProgramRecord:
        self.records.append(record)
        self.ops_held += record.op_count
        self.last_ts = record.ts
        for op in record.ops:
            if op.get("op") in _DATUM_OPS:
                # 🔴 A DATUM'S IDENTITY IS ITS NAME, NOT ITS `id` (measured
                # on the owner's live Revit, 03.09.2026). `id` lives
                # INSIDE the program: every turn that declares levels
                # calls them `level1`/`level2`. Deduplicating by `id`
                # meant "the first level with this number — forever": the
                # session's datum store got stuck on SIX names captured
                # in old turns («Кровля сарая», «KIR проба», «KIR_GAP_*»),
                # and everything later went into `datums_dropped`
                # SILENTLY.
                #
                # The price was not bookkeeping: datums are read by the
                # self-check, the batch judge, and the viewer base's
                # signature. An apartment with five built rooms got
                # «HAB000: model has no rooms», because its level never
                # made it into the store, and it looked like "the judge
                # didn't read it".
                #
                # The name is the very quantity by which a level is
                # looked up with the `{"by": "name"}` selector; `id` does
                # not work for this BY CONSTRUCTION.
                _имя = op.get("name")
                token = (f"{op.get('op')}:имя:{_имя}" if _имя
                         else f"{op.get('op')}:id:{op.get('id')}")
                if token in self._datum_keys:
                    continue
                if len(self.datums) >= _max_datums():
                    self.datums_dropped += 1
                    continue
                self._datum_keys.add(token)
                self.datums.append(op)
        self._evict()
        return record

    def _evict(self) -> None:
        """Eviction from the head. What is evicted IS COUNTED, not forgotten."""
        max_programs = _max_programs()
        max_ops = _max_ops()
        while self.records and (
                len(self.records) > max_programs or self.ops_held > max_ops):
            gone = self.records.pop(0)
            self.ops_held -= gone.op_count
            self.programs_evicted += 1
            self.ops_evicted += gone.op_count
            # The index is cleared together with the program: a dangling
            # seq would make the reader draw emptiness and stay silent
            # about it.
            for seqs in self.level_index.values():
                if seqs and seqs[0] == gone.seq:
                    seqs.pop(0)
                elif gone.seq in seqs:
                    seqs.remove(gone.seq)
            if self.indexed_upto < gone.seq + 1:
                self.indexed_upto = gone.seq + 1

    # -- read ------------------------------------------------------------
    def pending(self) -> list[ProgramRecord]:
        """Programs the reader has not reached yet."""
        return [r for r in self.records if r.seq >= self.indexed_upto]

    def by_seqs(self, seqs: Iterable[int]) -> list[ProgramRecord]:
        wanted = set(seqs)
        return [r for r in self.records if r.seq in wanted]

    def advance(self, seq: int, stage: str) -> ProgramRecord | None:
        """Advance one record's stage. Returns the new record or `None`.

        `None` means "did not move", and there are THREE different
        reasons for this, none of which is a caller error: the record
        does not exist (evicted), the stage is unknown, the transition is
        forbidden by the law below.

        THE TRANSITION LAW, chosen so that a late answer cannot downgrade
        an outcome already established:

        * along the main line — FORWARD only (`planned → … → accepted`);
        * into a side stage — from the main line, ONCE; a side stage can
          name either absence/unknown or a proven partial effect;
        * an ordinary transition out of a side stage — NOWHERE. A side
          stage is terminal: "no evidence" does not turn back into
          "built" because someone called back. The one exception does not
          live here but in a separate `reconcile_late_commit`: it
          requires an operation id linked in advance and a verified late
          receipt with that same id.

        Monotonicity here is not a matter of taste. The bridge's answers
        arrive out of order (measurement of 16.08: the answer to an
        in-flight request arrived on a NEIGHBORING socket 32 s after the
        window was reopened), and without the law a late `dispatched`
        would overwrite an honest `committed`.

        🔴 THE THIRD TERM OF THE LAW WAS ADDED ON 24.08.2026, AND ITS
        ABSENCE WAS ERASING A REALLY BUILT BUILDING. Two audit findings,
        both reproduced with prod functions on the same slot:

          · CHUNKS: chunk 1 committed, chunk 2 was refused BEFORE taking
            effect — the program's combined record went into
            `refused_pre_effect`, and `built()` lost walls already
            standing in the model. Meanwhile the same turn's receipt said
            the opposite: "chunks 1..k are ALREADY IN THE MODEL and NOT
            ROLLED BACK";
          · PHASES: phase k did not link by reference across the
            boundary — phase k's body was never called at all, the slot
            still pointed at phase k-1's record in `committed`, and it
            was moved into a terminal refusal.

        The stage name states the fact word for word: `refused_pre_effect`
        means "refused BEFORE taking effect". Coming from `committed`,
        this is a LIE, not a loss of precision. Exactly the same for
        `running_unknown`: the law declared in `serving.py` ("a later
        error can weaken the EVIDENCE, but has no right to rewrite a
        KNOWN effect into an unconfirmed one") stood in one place and did
        not act in another.

        The journal's readers — the building's judge, the clash batch,
        the viewer's `base_digest` — believed the wrong thing, and the
        model, asked "what is standing", got back "nothing" and built a
        SECOND TIME.
        """
        if stage not in STAGES:
            return None
        for i, rec in enumerate(self.records):
            if rec.seq != seq:
                continue
            if rec.stage in _SIDE_STAGES:
                return None
            if rec.stage in BUILT_STAGES and stage in _SIDE_STAGES:
                # A complete built program is not weakened either to
                # absence/unknown or to a partial effect.
                return None
            if stage in _MAIN_STAGES and _RANK[stage] <= _RANK.get(rec.stage, 0):
                return None
            moved = replace(rec, stage=stage)
            self.records[i] = moved
            return moved
        return None

    def bind_operation_id(
        self,
        seq: int,
        operation_id: str,
    ) -> ProgramRecord | None:
        """Link the exact transport operation before it may be sent.

        This is deliberately separated from :meth:`advance`: linking does
        not assert an execution phase and does not create a back door out
        of a terminal side stage. A chunked program can link several
        different ids; one id can belong to only one stored program of
        the session.
        """

        exact = _operation_id(operation_id)
        if exact is None:
            return None
        if any(exact in rec.operation_ids and rec.seq != seq
               for rec in self.records):
            return None
        for i, rec in enumerate(self.records):
            if rec.seq != seq:
                continue
            if exact in rec.operation_ids:
                return rec
            if rec.stage not in {"planned", "grounded", "dispatched"}:
                return None
            moved = replace(
                rec,
                operation_ids=(*rec.operation_ids, exact),
            )
            self.records[i] = moved
            return moved
        return None

    def reconcile_late_commit(
        self,
        operation_id: str,
        receipt_digest: str,
    ) -> tuple[ProgramRecord, bool] | None:
        """Admit an already-authenticated late commit into the building's
        truth.

        Ordinary ``advance`` leaves every side stage terminal. This is
        the single narrow exception, and it requires an operation id
        linked before sending, and the digest of a verified receipt.
        Legacy records have no id, so they are deliberately not matched
        by seq, plan digest, or time.
        """

        exact = _operation_id(operation_id)
        if (exact is None or not isinstance(receipt_digest, str)
                or len(receipt_digest) != 64
                or any(char not in "0123456789abcdef"
                       for char in receipt_digest)):
            return None
        matches = [
            (i, rec) for i, rec in enumerate(self.records)
            if exact in rec.operation_ids
        ]
        if len(matches) != 1:
            return None
        index, rec = matches[0]
        # One receipt proves one transport operation. If the authored
        # program went out as several chunks, this journal does not have
        # the complete set of their terminal outcomes and must leave the
        # record unknown until a separate, full reconciliation.
        if len(rec.operation_ids) != 1:
            return None
        if rec.stage in BUILT_STAGES:
            if (rec.late_receipt_digest
                    and rec.late_receipt_digest != receipt_digest):
                return None
            return rec, False  # an idempotent repeat of the same truth about the commit
        if rec.stage != "running_unknown":
            return None
        moved = replace(
            rec,
            stage="committed",
            late_receipt_digest=receipt_digest,
        )
        self.records[index] = moved
        return moved, True

    def stage_census(self) -> dict[str, int]:
        """How many records are at each stage. Zero is NOT printed.

        An empty stage and a stage the instrument does not count here are
        different facts; printing `committed: 0` next to honest numbers
        would mean presenting a zero of the quantity as a result. A
        missing key reads unambiguously: there are no such records.
        """
        census: dict[str, int] = {}
        for rec in self.records:
            census[rec.stage] = census.get(rec.stage, 0) + 1
        return census

    def built(self) -> list[ProgramRecord]:
        """Only what is provably STANDING in the model."""
        return [r for r in self.records if r.is_built]

    def standing(self) -> list[ProgramRecord]:
        """What was declared, minus what was cancelled.

        Between `records` and `built`: a program that never reached the
        model, or was rolled back, is no longer an intent — the author no
        longer meant it. A partially executed one cannot be returned
        whole either: that would attribute un-built operations to the
        model. But `planned`/`dispatched` can still become a building, so
        they remain.
        """
        return [r for r in self.records if r.stage not in _SIDE_STAGES]

    def stats(self) -> dict[str, Any]:
        return {
            "schema": JOURNAL_SCHEMA,
            "programs": len(self.records),
            "ops": self.ops_held,
            "datums": len(self.datums),
            "datums_dropped": self.datums_dropped,
            "programs_evicted": self.programs_evicted,
            "ops_evicted": self.ops_evicted,
            "levels": len(self.level_index),
            "indexed_upto": self.indexed_upto,
            "next_seq": self.next_seq,
        }

    def summary(self) -> dict[str, Any]:
        """A summary of the DECLARED, by floor and by operation.

        The word is chosen deliberately. "What was built" cannot be said
        here: the journal is filled before the write, and Revit will
        still reject some of the programs.
        """
        return {
            "schema": JOURNAL_SCHEMA,
            "stage": "planned",
            "assertion": "self_reported",
            "title_ru": "ЗАЯВЛЕНО программами сессии (не «построено»)",
            "levels": [{"level": name, "declared": self.level_tally[name]}
                       for name in sorted(self.level_tally)],
            "by_op": dict(sorted(self.op_tally.items())),
            "programs": len(self.records),
            "total": sum(self.op_tally.values()),
            "programs_evicted": self.programs_evicted,
        }


_LOCK = threading.Lock()
#: LRU over sessions: a live service holds a few devices, not a hundred.
_SESSIONS: "OrderedDict[SessionKey, SessionJournal]" = OrderedDict()

#: TOMBSTONES OF EVICTED SESSIONS — because a silent loss is
#: indistinguishable from "this never happened". The 16.08 audit
#: measurement: the ninth session evicted the first, and `stats()`
#: returned `programs_evicted: 0` — the counter left ALONG WITH the
#: session it was counting. This is our form of "a zero of a quantity
#: the instrument does not count here is not a result", except this time
#: the zero was not in the instrument but in the store.
#:
#: A tombstone carries ONLY a count and a time: program bodies are not
#: stored, otherwise "a bounded store" would come back as a leak under a
#: different name. The tombstones themselves are also bounded — by the
#: same ceiling as the sessions.
_TOMBSTONES: "OrderedDict[SessionKey, dict[str, Any]]" = OrderedDict()


def _evict_session(key: SessionKey, journal: SessionJournal) -> None:
    """Remove a session from the store, LEAVING a trace behind. Called under `_LOCK`."""
    _TOMBSTONES[key] = {
        "programs": len(journal.records),
        "ops": journal.ops_held,
        "programs_evicted": journal.programs_evicted,
        "last_ts": journal.last_ts,
        "next_seq": journal.next_seq,
    }
    while len(_TOMBSTONES) > _max_sessions():
        _TOMBSTONES.popitem(last=False)


def _make_room() -> None:
    """Free up space for a new session. Called under `_LOCK`."""
    while len(_SESSIONS) > _max_sessions():
        gone_key, gone = _SESSIONS.popitem(last=False)
        _evict_session(gone_key, gone)


def was_evicted(key: SessionKey) -> dict[str, Any] | None:
    """Whether this session was evicted — and what was in it.

    A THIRD OUTCOME alongside `get()`: `get` returns `None` both when the
    session never existed and when it was evicted. A reader indifferent
    to these two cases need not ask; a reader drawing a conclusion about
    the BUILDING must, or it will declare emptiness where there was a
    loss.
    """
    with _LOCK:
        found = _TOMBSTONES.get(key)
        return dict(found) if found is not None else None


def _снимок(значение: Any) -> Any:
    """A deep copy of FLAT containers. Foreign objects are left untouched.

    🔴 WHY NOT `dict(op)` (F-180, confirmed by execution on 04.09.2026).
    The docstring below promised "the journal must outlive the caller",
    but the copy was SHALLOW: nested coordinates, contours, and selectors
    stayed shared. Measurement: the author edits their own dict AFTER the
    write —

        p0_mm in the journal        [999999, 0]        overwritten
        contour.outer.points_mm     [[777777, 0], …]   overwritten

    The journal is what the batch judge and the viewer rebuild the
    building from, meaning the author's edit was silently rewriting the
    HISTORY of what had already been recorded.

    THE PRICE IS MEASURED, NOT ASSUMED (on realistic ops with a nested
    contour): 20 ops — 0.165 ms, 500 — 4.3 ms, 5000 — 53 ms. Against
    `dict()` that is ×15–20; against `copy.deepcopy` it is THREE TIMES
    CHEAPER (which runs 0.371 / 9.6 / 150 ms). On the author's live turn
    (1–25 ops) the price is under a fifth of a millisecond, and it buys
    the record no longer being shared.

    Non-containers are returned as-is: deep-copying someone else's object
    would mean deciding on its behalf, and operations carry only
    JSON-compatible data.
    """
    if isinstance(значение, dict):
        return {k: _снимок(v) for k, v in значение.items()}
    if isinstance(значение, list):
        return [_снимок(v) for v in значение]
    if isinstance(значение, tuple):
        return tuple(_снимок(v) for v in значение)
    return значение


def _normalise_ops(program: Any) -> tuple[Mapping[str, Any], ...]:
    """`PlannedProgram` | {'ops': [...]} | a list of operations -> a tuple
    of dicts.

    The copy is made HERE, once, and it is DEEP: the journal must outlive
    the caller, and the caller is free to change their own dict
    afterward — including nested coordinates and contours (see
    `_снимок`).
    """
    raw: Any
    if hasattr(program, "to_ops"):
        raw = program.to_ops()
    elif isinstance(program, Mapping):
        raw = program.get("ops") or ()
    elif isinstance(program, Sequence) and not isinstance(program, (str, bytes)):
        raw = program
    else:
        return ()
    return tuple(_снимок(dict(op)) for op in raw if isinstance(op, Mapping))


#: Keys for which a restore has already been tried in THIS process. The
#: store is read once per key: a session with no history gets the answer
#: "restored 0", and repeating this for every program would mean paying
#: for a disk read for a known zero.
_RESTORE_TRIED: set = set()

# ---------------------------------------------------------------------------
# FIRST-LOAD LOCK (RT-27)
# ---------------------------------------------------------------------------
#
# 🔴 WHAT IS BEING CLOSED HERE. `_RESTORE_TRIED` is an ordinary set, and
# the `add(key)` mark used to be set RIGHT AFTER the check, BEFORE
# reading the store. Between the mark and the end of the read lies a
# whole disk window, and a second thread in that window would see
# "already tried", NOT WAIT, and start an EMPTY session with `seq` from
# zero. When the first thread finished reading, `restore` honestly
# refused it with `live_session_present` — and the restored building was
# silently thrown away, and a repeat restore was no longer possible: the
# mark is already set. Measurement, two programs on one key, restoring 5
# programs from disk:
#
#     CONTROL, sequential  : records 7  next_seq 7  restored from disk 5
#     EXPERIMENT, parallel : records 2  next_seq 2  restored from disk 0
#
# A loss of the same kind as with `_evict_session`: a history with a hole
# looks exactly like an honest one.
#
# 🔴 WHY `threading.Lock`, AND NOT A FILE LOCK LIKE IN
# `decompile/journal_store.py`. There, a FILE stands under the lock, and
# "read-tally-replace" is done by different PROCESSES — a lock in a
# process's memory is invisible to them entirely. Here the subject is
# different, and this is VERIFIED BY THE CODE, not assumed: what is
# guarded are `_RESTORE_TRIED` and `_SESSIONS`, both module globals, i.e.
# they live inside a single interpreter; `restore()` ONLY READS the
# store (`read_events` + `replay`) and does not write a single byte to
# disk. So this race does not have a second process: it restores its own
# copy into its own memory, and its records land through `append_line`
# with `O_APPEND` — the subject of other gates. A file lock here would be
# guarding something that does not happen in the file.
#
# A LOCK PER KEY, NOT ONE FOR EVERYONE, AND THIS IS A MEASUREMENT, NOT
# TASTE. Median time for one restore on this machine: 18.0 ms at 1,000
# store lines, 218.4 ms at 10,000. One shared lock would delay by that
# much the first program of SOMEONE ELSE'S session, one this key is
# irrelevant to.
#
# THE ENTRY IS DELETED AFTER THE RESTORE: once the mark is in
# `_RESTORE_TRIED`, the lock for this key is no longer needed, and a
# second, unboundedly growing dict next to `_RESTORE_TRIED` would be a
# second leak instead of one. A thread that has already taken the lock
# object holds a reference to it — deleting it from the dict neither
# wakes it nor breaks it: it will take the lock, see the mark, and return
# `None`.
_RESTORE_LOCKS: dict[SessionKey, threading.Lock] = {}
_RESTORE_LOCKS_GUARD = threading.Lock()


def _restore_lock(key: SessionKey) -> threading.Lock:
    with _RESTORE_LOCKS_GUARD:
        lock = _RESTORE_LOCKS.get(key)
        if lock is None:
            lock = _RESTORE_LOCKS[key] = threading.Lock()
        return lock


def _restore_once(key: SessionKey) -> dict[str, Any] | None:
    """Restore the session journal from the store — ONCE per key, per
    process.

    🔴 WHY THIS WAS NEEDED AT ALL. `restore` was written, covered by
    tests, and CALLED BY NOBODY — measurement of 23.08.2026: zero
    callers. That is, the building's memory between service restarts
    existed on disk and did not exist in operation: after a restart, "the
    whole building" started from an empty place, while the past turns'
    programs lay right there, handed to no one. This is our generic
    class — built, covered, not wired in.

    WHY RIGHT HERE. `append` is the only place where the session key
    first becomes known to the process. Earlier than it, there is
    nowhere to put the restore; later, the building has already started
    over.

    WHY BEFORE THE LOCK. `restore` takes `_LOCK` itself; calling it from
    under the lock would deadlock on the very first program. Reading
    `_SESSIONS` without a lock is harmless here: the worst case is one
    extra restore attempt, which `restore` will reject on its own
    ("this session has already been lived by this process — restoring on
    top of it would duplicate the building"). Duplication is closed off
    INSIDE the restore, not by this condition.

    THE RESTORE DOES NOT STAY SILENT. A restored building changes what
    the verdict and the clash check pass judgment on; a silent restore
    would read as "this session built exactly this much".
    """
    lock = _restore_lock(key)
    with lock:
        try:
            return _restore_once_locked(key)
        finally:
            with _RESTORE_LOCKS_GUARD:
                _RESTORE_LOCKS.pop(key, None)


def _restore_once_locked(key: SessionKey) -> dict[str, Any] | None:
    """The body of the restore, UNDER THE KEY'S LOCK (see
    `_RESTORE_LOCKS`).

    The lock is held both while checking the mark and while reading the
    store: taken separately, they left a window in which a second thread
    would start an empty session on top of one not yet restored.
    """
    if key in _RESTORE_TRIED:
        return None
    _RESTORE_TRIED.add(key)
    # 🔴 THE LOCAL DUPLICATE WAS REMOVED ON 02.09.2026, AND THE OLD
    # RATIONALE HAD OUTLIVED ITS TRUTH. It used to say: a module-level
    # `from kir import env` breaks purity, and the guard
    # `test_live_plan_stream::OneWayTests` turns red because of it.
    # Today the module-level import stands (line 64, an environment-name
    # move), and the guard is GREEN — 6 passed, verified by execution.
    # The local import, however, WAS SHADOWING the module-level one, and
    # another guard correctly turned red over it:
    # `test_authority_boundaries` — "journal.py::_restore_once shadows
    # module import env". Two names for one module in one file are two
    # carriers, and the question "which one gets read" has no answer
    # from the text alone.
    if env.get("KIR_JOURNAL_RESTORE", "1") == "0":
        return None
    try:
        got = restore(key)
    except Exception:  # noqa: BLE001 — a restore has no right to break the turn
        logger.debug("journal restore raised", exc_info=True)
        return None
    if got.get("restored"):
        logger.info("journal: поднято %s программ со склада для ключа %s "
                    "(по стадиям %s)", got.get("restored"), key,
                    got.get("by_stage"))
        if got.get("programs_by_name"):
            # The same carrier as for the refusal: the receipt must learn
            # about the pile-up BY NAME even when its own journal
            # restored fine. WARNING for the same reason — there is
            # something for a person to decide.
            _remember_restore_note(key, got)
            logger.warning(
                "journal: подъём состоялся (%s программ), но РЯДОМ на складе "
                "лежат ещё %s программ под именем «%s» без идентичности "
                "документа; они НЕ подняты",
                got.get("restored"), got.get("programs_by_name"),
                got.get("document_name"))
    elif got.get("refused") == FOREIGN_JOURNAL_REFUSAL:
        # WARNING, not INFO: this is the only restore refusal a person
        # has something to decide about. The previous version, at this
        # very spot, printed "restored 194 programs" — and was at ease.
        _remember_restore_note(key, got)
        logger.warning(
            "journal: %s — на складе %s программ под именем «%s» без "
            "идентичности документа; НЕ подняты. %s",
            FOREIGN_JOURNAL_REFUSAL, got.get("programs_by_name"),
            got.get("document_name"), got.get("next_step_ru"))
    elif got.get("refused") not in (None, "live_session_present"):
        logger.info("journal: подъём НЕ состоялся (%s) — здание этой сессии "
                    "начнётся с пустого места", got.get("refused"))
    return got


#: WHAT THE RESTORE OF THIS KEY SAID — for the RECEIPT, not for a debug
#: log.
#:
#: The reason is exactly the one for which `journal_stage` lives nearby
#: in `serving._with_outcome`: "programs 0" reads to the building's
#: judge as "nothing was built", and there would be nothing outside to
#: tell it apart from "the journal of the same-named document was NOT
#: restored". A dict keyed by session, not a ContextVar: the restore
#: happens inside `append`, i.e. in a thread that knows nothing about the
#: turn.
#:
#: THERE IS A CEILING, AND IT IS NOT DECORATION: a dict keyed by session
#: next to the unboundedly growing `_RESTORE_TRIED` would be a SECOND
#: leak instead of one (the same argument as for `_RESTORE_LOCKS`). There
#: are as many entries as there are keys for one process per shift — 64
#: with margin, the oldest gets evicted.
_RESTORE_NOTES: "OrderedDict[SessionKey, dict[str, Any]]" = OrderedDict()
_RESTORE_NOTES_MAX = 64


def _remember_restore_note(key: SessionKey, note: Mapping[str, Any]) -> None:
    _RESTORE_NOTES[key] = dict(note)
    _RESTORE_NOTES.move_to_end(key)
    while len(_RESTORE_NOTES) > _RESTORE_NOTES_MAX:
        _RESTORE_NOTES.popitem(last=False)


def restore_note(key: SessionKey) -> dict[str, Any] | None:
    """The named outcome of the restore for this key, if there is one."""
    return _RESTORE_NOTES.get(key)


def append(key: SessionKey, program: Any, *, plan_digest: str = "",
           author_digest: str = "", intent: str = "",
           source: str = "", operation_id: str = "") -> ProgramRecord | None:
    """Write a program into the session journal. Never raises exceptions."""
    ops = _normalise_ops(program)
    if not ops:
        return None
    if key not in _SESSIONS:
        # THE LOCK ORDER IS ONE AND ONLY ONE: `_RESTORE_LOCKS[key]` ->
        # `_LOCK`. The restore takes `_LOCK` inside itself, so calling it
        # FROM UNDER `_LOCK` is not allowed (the "WHY BEFORE THE LOCK" in
        # the restore's docstring says so too), and the module has no
        # reverse path — taking `_LOCK` and then the key's lock.
        _restore_once(key)
    with _LOCK:
        journal = _SESSIONS.get(key)
        if journal is None:
            journal = SessionJournal(key=key)
            _SESSIONS[key] = journal
            _make_room()
        _SESSIONS.move_to_end(key)
        exact_operation_id = _operation_id(operation_id)
        record = ProgramRecord(
            seq=journal.next_seq,
            ts=time.time(),
            ops=ops,
            plan_digest=str(plan_digest or getattr(program, "plan_digest", "") or ""),
            author_digest=str(author_digest or ""),
            intent=str(intent or getattr(program, "intent", "") or "")[:200],
            source=str(source or ""),
            operation_ids=((exact_operation_id,)
                           if exact_operation_id is not None else ()),
        )
        journal.next_seq += 1
        stored = journal.append(record)
    # 🔴 THE DISK WRITE IS OUTSIDE `_LOCK` AND AFTER MEMORY, and both
    # decisions are deliberate. Outside the lock: `fsync` costs
    # milliseconds (measured: 5.4–6.2 ms per program), and holding the
    # whole store's mutex on it would mean serializing all sessions
    # through the disk. After memory: the hot path does not wait on the
    # disk, and the store is the main reader. The store's failure is NOT
    # checked: it is fail-open by construction and has already spoken
    # for itself in the log.
    _store_program(key, stored)
    return stored


def _store_program(key: SessionKey, record: ProgramRecord) -> None:
    """Hand the record off to the durable store. NEVER raises."""
    try:
        from kir.live import journal_store
        journal_store.record_program(key, record)
    except Exception:  # noqa: BLE001 — the turn is worth more than a line
        pass


def remember_sections(key: SessionKey, sections: Any) -> None:
    """Remember this session's document type geometry. Never raises.

    A separate entry point, not a field of `append`, deliberately: the
    program lands in the journal BEFORE ground has come back from the
    bridge (`serving`: publish at line 1362, the snapshot at line 1387),
    and tying them into one call would mean either delaying the write of
    the building's source code or losing the first turn's sections.
    """
    if sections is not None and not isinstance(sections, dict):
        return
    with _LOCK:
        journal = _SESSIONS.get(key)
        if journal is None:
            journal = SessionJournal(key=key)
            _SESSIONS[key] = journal
            _make_room()
        _SESSIONS.move_to_end(key)
        journal.sections = None if sections is None else dict(sections)


def advance(key: SessionKey, seq: int, stage: str) -> bool:
    """A record's stage became known. Never raises.

    Returns whether it moved. `False` is not a caller error: the record
    could have been evicted, or the transition could be forbidden by the
    monotonicity law (`SessionJournal.advance`). The caller does not need
    to know which of the reasons fired; what matters is not pretending
    that it moved.
    """
    if not isinstance(seq, int) or not stage:
        return False
    with _LOCK:
        journal = _SESSIONS.get(key)
        if journal is None:
            return False
        moved = journal.advance(seq, str(stage)) is not None
    # We write ONLY a transition that actually happened. Writing a
    # rejected one would hand replay a stage that never existed in the
    # building — and the monotonicity law would then have to be repeated
    # in the store as a second instance.
    if moved:
        try:
            from kir.live import journal_store
            journal_store.record_stage(key, seq, str(stage))
        except Exception:  # noqa: BLE001 — the turn is worth more than a line
            pass
    return moved


def bind_operation_id(key: SessionKey, seq: int, operation_id: str) -> bool:
    """Link the transport identity to the program before sending.

    The in-memory transition is authoritative for the current process;
    the durable store remains an existing fail-open observer of the
    journal. So a failure to write to disk does not block the Revit
    turn, but it also cannot invent a successful link during replay.
    """

    if not isinstance(seq, int):
        return False
    with _LOCK:
        journal = _SESSIONS.get(key)
        if journal is None:
            return False
        before = next((rec for rec in journal.records if rec.seq == seq), None)
        moved = journal.bind_operation_id(seq, operation_id)
        if moved is None:
            return False
        changed = before is not moved
    if changed:
        try:
            from kir.live import journal_store
            journal_store.record_operation(key, seq, operation_id)
        except Exception:  # noqa: BLE001 — observer cannot break a write
            pass
    return True


def reconcile_late_commit(
    key: SessionKey,
    operation_id: str,
    receipt: Any,
    *,
    identity_verified: bool,
) -> bool:
    """Lift ``running_unknown`` only with a matching authenticated
    receipt.

    ``identity_verified`` is a strict assertion of authority from the
    host, which authenticated the client and checked the full
    OperationIdentity. The receipt must still carry exactly this
    operation id and a fully committed outcome. The ordinary
    :func:`advance` is unchanged, and records from old schemas with no
    operation id cannot pass through this path.
    """

    exact = _operation_id(operation_id)
    if exact is None:
        return False
    receipt_digest = _verified_late_commit_digest(
        exact, receipt, identity_verified=identity_verified)
    if receipt_digest is None:
        return False
    with _LOCK:
        journal = _SESSIONS.get(key)
        if journal is None:
            return False
        reconciled = journal.reconcile_late_commit(exact, receipt_digest)
        if reconciled is None:
            return False
        record, changed = reconciled
    if changed:
        try:
            from kir.live import journal_store
            journal_store.record_stage(
                key,
                record.seq,
                "committed",
                operation_id=exact,
                receipt_digest=receipt_digest,
                reconciled=True,
            )
        except Exception:  # noqa: BLE001 — observer cannot break receipt ACK
            pass
    return True


def get(key: SessionKey) -> SessionJournal | None:
    with _LOCK:
        return _SESSIONS.get(key)


def sessions() -> tuple[SessionKey, ...]:
    with _LOCK:
        return tuple(_SESSIONS)


def reset(key: SessionKey | None = None) -> None:
    """Forget a session entirely — including its tombstone.

    The tombstone is removed deliberately: `reset` means "this never
    happened", while leaving a trace behind would mean "it happened and
    was lost". Two different facts, and they must not be conflated here
    for exactly the reason that the whole point of a tombstone is to
    distinguish them.
    """
    with _LOCK:
        if key is None:
            _SESSIONS.clear()
            _TOMBSTONES.clear()
            _RESTORE_NOTES.clear()
        else:
            _SESSIONS.pop(key, None)
            _TOMBSTONES.pop(key, None)
            _RESTORE_NOTES.pop(key, None)


#: THE STAGE MAP FOR A DISK RESTORE. Identical everywhere except one
#: place — and that place is the whole point of the map.
#:
#: 🔴 `dispatched` IN A LIVE SESSION MEANS "IN FLIGHT RIGHT NOW". After
#: the process crashes, nothing is left in flight: Revit's answer is
#: lost forever, and there is nothing left to wait for it. Restoring such
#: a record as `dispatched` would mean offering the reader to wait for an
#: answer that will never come — a subtle kind of lie, worse than
#: silence. An honest name for "no evidence" already exists in this
#: dictionary, and it was set up for exactly this case: `running_unknown`
#: — "not 'not built', but 'we don't know', and a retry is forbidden".
#: The record could have gone through, so it cannot be collapsed into
#: "not built" either.
_RESTORE_STAGE_MAP = {"dispatched": "running_unknown"}


def restore(key: SessionKey, *, path: Any = None) -> dict[str, Any]:
    """Restore a session from disk. Returns a census, NEVER raises.

    🔴 WHY, BY THE MEASUREMENT OF 19.08.2026.
    `journal_store.replay()`/`read_events()` were written, covered by
    tests, and **called from nowhere**: events were being laid down on
    disk with `fsync` (a live file of 589 KB), and the building still
    vanished along with the process. The store worked as forensics, not
    as memory.

    🔴 A LIVE SESSION IS NEVER OVERWRITTEN. Restoring on top of records
    already lived through by this process would duplicate the building:
    the disk and the memory carry the same programs, and stitching them
    together by `seq` would mean believing that numbering survives a
    restart. Such a call refuses and states how many records got in the
    way.

    Returns: `restored` (how many programs were restored), `by_stage`
    (the census), `outcome_unknown` (how many were restored with a lost
    outcome — read this first), `reclassified` (how many `dispatched`
    became `running_unknown`), `path`.
    """
    try:
        from kir.live import journal_store
        # 🔴 A PAIR, NOT A LIST — this tree's §18.2 law, and it was
        # bought right here: the first version of `created_ledger`
        # returned only lines, the reader got `Permission denied` and
        # returned emptiness, and "could not look" became
        # indistinguishable from "there is nothing". The first version
        # of THIS function stepped on the exact same stone.
        # The path that is remembered is THE ONE THAT WAS READ. The
        # first version printed `store_path()` into the census
        # regardless of the argument — that is, it named a file it had
        # not looked at.
        read_from = str(path if path is not None
                        else (journal_store.store_path() or ""))
        rows, refusal = journal_store.read_events(path)
        if refusal:
            # A store failure PROPAGATES UPWARD. "Restored 0" with no
            # cause is exactly that indistinguishable zero.
            return {"restored": 0, "refused": "store_unreadable",
                    "detail": refusal, "path": read_from}
        raw = journal_store.replay(rows, key=key)
        # 🔴 A SAME-NAMED FOREIGN JOURNAL IS COUNTED HERE, NOT BY A
        # SECOND DISK READ. `rows` is already in hand; a second
        # `read_events` would cost 218 ms on a store of 10,000 lines
        # (measured in `_RESTORE_LOCKS`) and, worse, would read a
        # DIFFERENT snapshot of the file — that is, it would be
        # answering about a different store.
        legacy_rows: tuple[dict[str, Any], ...] = ()
        legacy_key = named_only_key(key)
        # 🔴 THIS IS COUNTED ALWAYS, NOT ONLY WHEN ONE'S OWN JOURNAL IS
        # EMPTY (08.09.2026, "NOT done" item #1 of wave 9). The previous
        # condition was `not raw`: a successful restore of one's OWN
        # journal stayed silent about a pre-reform pile of the same name
        # lying right next to it. The silence here is of the same kind
        # this whole fix was treating: a person sees "restored 7" and
        # does not know that 194 programs from their previous session
        # were NOT restored — that is, "the building is incomplete" is
        # indistinguishable from "the building was always like this".
        #
        # NO SECOND DISK READ APPEARS: `rows` is already in hand, and
        # this is the same argument by which the count sits here rather
        # than in a separate `read_events`.
        if document_identity_of(key[1] if len(key) > 1 else ""):
            legacy_rows = journal_store.replay(rows, key=legacy_key)
    except Exception as exc:  # noqa: BLE001 — a restore has no right to break the turn
        logger.debug("journal restore failed", exc_info=True)
        return {"restored": 0, "refused": "store_unreadable",
                "detail": type(exc).__name__}
    with _LOCK:
        live = _SESSIONS.get(key)
        if live is not None and live.records:
            return {"restored": 0, "refused": "live_session_present",
                    "live_records": len(live.records),
                    "detail": ("сессия уже прожита этим процессом — подъём "
                               "поверх удвоил бы здание")}
        journal = SessionJournal(key=key)
        by_stage: dict[str, int] = {}
        reclassified = 0
        for body in raw:
            ops = _normalise_ops({"ops": body.get("ops") or []})
            if not ops:
                continue
            on_disk = str(body.get("stage") or "planned")
            stage = _RESTORE_STAGE_MAP.get(on_disk, on_disk)
            if stage != on_disk:
                reclassified += 1
            if stage not in STAGES:
                # An unfamiliar stage is not a reason to guess: the
                # weakest value is more honest than a plausible-looking
                # one.
                stage = "planned"
            rec = ProgramRecord(
                seq=int(body.get("seq") or 0),
                ts=time.time(),
                ops=ops,
                plan_digest=str(body.get("plan_digest") or ""),
                author_digest=str(body.get("author_digest") or ""),
                intent=str(body.get("intent") or "")[:200],
                source=str(body.get("source") or ""),
                operation_ids=tuple(
                    item for item in (body.get("operation_ids") or ())
                    if _operation_id(item) is not None),
                late_receipt_digest=str(
                    body.get("late_receipt_digest") or ""),
                stage=stage,
                restored_from_disk=True,
            )
            # 🔴 THROUGH THE JOURNAL'S DOOR, NOT INTO THE LIST (F-181/F-159,
            # class П5-В, 29.08.2026). `records.append` builds a LIST; the
            # journal is a list PLUS bookkeeping: `ops_held`, `last_ts`,
            # `datums`/`_datum_keys`, eviction. The restore was building
            # none of this, and the restored session differed from a
            # lived-through one in EVERYTHING except the record count.
            # Measurement: the live path gives `ops_held=2, datums=1`;
            # the restore gives 0 and 0.
            #
            # The consequence for the VIEWER is more expensive than the
            # bookkeeping itself (F-159): `base_digest` was computed over
            # EMPTY datums, and the next delta was counted from a base
            # the client does not have. Measurement: the restored base's
            # signature `e0da6658…` against the live `1b8cac0d…` — "showed
            # a building with no floors".
            #
            # `append` does NOT touch `seq` (it accepts a ready-made
            # `ProgramRecord`), so the restore preserves the numbers from
            # disk — verified by running it.
            journal.append(rec)
            journal.next_seq = max(journal.next_seq, rec.seq + 1)
            by_stage[stage] = by_stage.get(stage, 0) + 1
        if not journal.records:
            if legacy_rows:
                # 🔴 NAME IT, DON'T RESTORE IT (08.09.2026). The store
                # holds records UNDER THE SAME NAME and with no identity.
                # There are two kinds of them, and there is nothing to
                # distinguish them with BY CONSTRUCTION: either it is the
                # same document from before the move to identity, or it
                # is a DIFFERENT document with the default name
                # ("Проект1"). Restoring it means agreeing to the second
                # kind, and that is exactly the memory leak between
                # documents the key was changed to fix. So the outcome is
                # a NAMED REFUSAL with a number, and the person decides
                # for themselves.
                return {
                    "restored": 0,
                    "refused": FOREIGN_JOURNAL_REFUSAL,
                    "programs_by_name": len(legacy_rows),
                    "document_name": document_name_of(legacy_key[1]),
                    "legacy_key": legacy_key,
                    "detail": (
                        f"на складе есть {len(legacy_rows)} программ под "
                        f"именем «{document_name_of(legacy_key[1])}», но без "
                        "идентичности документа. Это либо ЭТОТ документ до "
                        "08.09.2026, либо ДРУГОЙ документ с тем же именем по "
                        "умолчанию — различить их нечем, поэтому они НЕ "
                        "поднимаются. Здание этой сессии начинается с пустого "
                        "места"),
                    "next_step_ru": (
                        "если это ваш прежний документ — сохраните его и "
                        "откройте заново: с этого мига журнал ведётся по "
                        "тождеству документа, а не по имени"),
                    "by_stage": {}, "outcome_unknown": 0,
                    "reclassified": 0, "path": read_from}
            return {"restored": 0, "by_stage": {}, "outcome_unknown": 0,
                    "reclassified": 0, "path": read_from}
        _SESSIONS[key] = journal
        _SESSIONS.move_to_end(key)
        _make_room()
        return {
            "restored": len(journal.records),
            "by_stage": by_stage,
            # Read this FIRST: these programs' outcome is lost, and they
            # belong neither to "built" nor to "not built".
            "outcome_unknown": by_stage.get("running_unknown", 0),
            "reclassified": reclassified,
            # 🔴 A RESTORE NOW EVICTS, AND THIS IS COUNTED (F-181). The
            # journal's door calls `_evict()`, so a history longer than
            # the ceiling gets trimmed FROM THE HEAD — that is exactly
            # what ceilings are for. But the restore used to bring up
            # EVERYTHING, so the behavior has changed, and staying silent
            # about it would mean introducing a loss with no number.
            "programs_evicted": journal.programs_evicted,
            # 🔴 SUCCESS ALSO NAMES THE NEIGHBOR. A zero here is a FACT
            # ("there is nothing next to it"), not the absence of an
            # answer: from outside there would be nothing to tell "did
            # not look" from "looked and it was empty" with, and this is
            # a named class of this tree.
            "programs_by_name": len(legacy_rows),
            "document_name": document_name_of(legacy_key[1]),
            "next_step_ru": (
                "это история под ключом ПО ИМЕНИ (до 08.09.2026); поднять её "
                "нельзя — журнал ведётся по тождеству документа, и одноимённый "
                "чужой документ поднялся бы вместе с ней"
                if legacy_rows else ""),
            "path": read_from,
        }


def stats() -> dict[str, Any]:
    """The store's state. A loss IS COUNTED, it does not vanish along
    with the counter.

    `programs_evicted` for live sessions was already being summed up
    before — but it could not see a session evicted entirely BY
    CONSTRUCTION: the counter was stored inside the very thing being
    deleted. So a session's loss is counted SEPARATELY, from the
    tombstones, not from the living.
    """
    with _LOCK:
        census: dict[str, int] = {}
        for journal in _SESSIONS.values():
            for stage, count in journal.stage_census().items():
                census[stage] = census.get(stage, 0) + count
        return {
            "schema": JOURNAL_SCHEMA,
            "sessions": len(_SESSIONS),
            "programs": sum(len(j.records) for j in _SESSIONS.values()),
            "ops": sum(j.ops_held for j in _SESSIONS.values()),
            "programs_evicted": sum(
                j.programs_evicted for j in _SESSIONS.values()),
            "by_stage": census,
            "sessions_evicted": len(_TOMBSTONES),
            "programs_lost_with_sessions": sum(
                int(t.get("programs") or 0) for t in _TOMBSTONES.values()),
        }
