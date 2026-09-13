"""Wave A1 — live DECOMPILE orchestration over the injected bridge executor.

This is the *wiring* layer between the read-only Revit bridge and the frozen
offline compiler tail (``lift → fold → name → verify → passport``).  It owns
none of the compiler's semantics: it drives the bridge, persists every stage
artifact under ``out_dir``, and hands the assembled L0 + side indexes to the
existing offline stages.

Why a new module (not an extension of ``orchestrator.py``)
---------------------------------------------------------
``orchestrator.decompile`` is the *pure offline* composed pipeline: it takes an
already-materialized :class:`L0Document` in RAM and runs LIFT→passport through
the cache-disabled ``cached_lift_document_detailed`` contract.  A1 needs the
orthogonal concern of driving the bridge (executor, probe protocol, batching,
``status.json``, resume) and enables that same detailed-lift cache (64×
proven).  This module calls the bridge-facing extractors, persists their
products, and composes the frozen offline stages directly so timing, resume,
and cache policy remain live-orchestration concerns.

Bridge Load Contract (master-design Д1)
---------------------------------------
Every bridge call carries the existing per-stage budgets (target ≤2 s p95,
surfaced as ``slo_violations`` in status).  Between batches the orchestrator
``await asyncio.sleep(_YIELD_S)`` so the Revit UI thread breathes, and it
re-reads ``status.json`` for ``cancel_requested`` between batches — a set flag
is a clean stop that resumes later from the extract checkpoint and the
already-persisted side indexes.

Probe protocol (master-design Д2)
---------------------------------
A cheap per-category probe (count + max ElementId, one bridge command built
from :func:`extract.build_category_probe_cs`) is taken before and after each
side-index stage.  Divergence ⇒ the stage is *stale* ⇒ one automatic retry ⇒
still divergent ⇒ a typed refusal ``model_edited_during_decompile`` recorded in
``run.json``/``status.json``.  Contract for the operator: do not edit the model
during a run.

Invariants: I1 (no LOT31/RU hardcode — categories come from L0), I2 (every
failure is a typed result, never a bare exception into the caller), I4 (no
wall-clock in the deterministic artifacts; timestamps live only in status/run
metadata), I5 (nothing here imports on the hot path; the serving tool gates it),
I7 (paginated, budgeted, resumable — never a full-model brute force).
"""
from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from kir.contracts import RevisionProof
from kir.open_model import (
    OpenModelProfileError,
    capture_open_model_profile,
)
from kir.decompile.curtain_extract import (
    CurtainExtraction,
    build_curtain_extract_cs,
    extract_curtain_topology,
)
from kir.decompile.curve_extract import (
    CurveExtraction,
    build_curve_extract_cs,
    extract_curves,
)
from kir.decompile.annotation_extract import (
    ANNOTATION_CATEGORIES,
    AnnotationExtraction,
    build_annotation_extract_cs,
    extract_annotations,
    merge_annotations,
)
from kir.decompile.tag_extract import (
    TAG_CATEGORIES,
    TagExtraction,
    build_tag_extract_cs,
    extract_tags,
    merge_tags,
)
from kir.decompile.dimension_extract import (
    DIMENSION_CATEGORIES,
    DimensionExtraction,
    build_dimension_extract_cs,
    extract_dimensions,
    merge_dimensions,
)
from kir.decompile.join_extract import (
    JOIN_CATEGORIES,
    JoinExtraction,
    build_join_extract_cs,
    extract_joins,
    merge_joins,
)
from kir.decompile.mep_system_extract import (
    MEP_SYSTEM_CATEGORIES,
    MepSystemExtraction,
    build_mep_system_extract_cs,
    extract_mep_systems,
    merge_mep_systems,
)
from kir.decompile.census import CensusBalance, reconcile_census
from kir.decompile.dependencies import build_dependency_manifest
from kir.decompile.extract import (
    BridgeExecutor,
    DocumentRevisionError,
    ExtractionError,
    TemplateCompileError,
    build_category_probe_cs,
    extract_document,
    L0JSONLReader,
)
from kir.decompile.family_placement_extract import (
    FamilyPlacementExtraction,
    build_family_placement_extract_cs,
    parse_family_placement_index,
)
from kir.decompile.side_contract import (
    SideFailureKind,
    SideStageContractError,
    failure_element_id,
    failure_kind,
    receipts_summary_ru,
    reconcile_side_stage,
    relations_reach,
    record_element_id,
    resolved_typed_reason,
    summarize_side_failures,
)
from kir.decompile.fold import fold_document
from kir.decompile.group_extract import (
    GroupExtraction,
    build_group_extract_cs,
    parse_group_index,
)
from kir.decompile.geom_extract import (
    GeometryArtifactProof,
    GeometryExtraction,
    build_geometry_extract_cs,
    extract_geometry,
    merge_geometry_extractions,
)
from kir.decompile.honesty import (
    BuildStatuses,
    EquivalenceClaim,
    EquivalenceScope,
)
from kir.decompile.building_graph import building_graph_enabled
from kir.decompile.graph_store import (
    GRAPH_ARTIFACT_NAME,
    build_graph_for_run,
    write_graph,
)
from kir.decompile.journal import journal_enabled
from kir.decompile.journal_store import record_revision
from kir.decompile.lift_cache import (
    cached_lift_document_detailed,
    lift_cache_refusals,
)
from kir.decompile.merkle import merkle_enabled
from kir.decompile.merkle_report import building_report
from kir.decompile.name import name_document
from kir.decompile.passport import build_passport, passport_bytes
from kir.decompile.schema import (
    EXTRACT_TIMEOUT_MS,
    GeometryKind,
    L0Document,
)
from kir.decompile.sketch_extract import (
    ProfileExtraction,
    build_sketch_extract_cs,
    extract_sketch_profiles,
)
from kir.decompile.verify import verify_document


# ── Bridge Load Contract constants (Д1 / Д13) ───────────────────────────────
_YIELD_S = 0.2                 # inter-batch pause so the Revit UI thread breathes
_SLO_CALL_MS = 2_000           # target single-call latency (Д13 p95 ≤2 s)
_STATUS_NAME = "status.json"
_RUN_NAME = "run.json"
_SIDE_BATCH = 200              # ids per side-index bridge call (paginated, I7)
_REVISION_PROOF_NAME = "revision.proof.json"
_GEOMETRY_PROOF_NAME = "geometry.proof.json"
_SIDE_MANIFEST_NAME = "side_index.manifest.json"
_SIDE_MANIFEST_VERSION = "kir-decompile-side-manifest/1"
_REVISION_PROOF_VERSION = "document-revision/1"
_OPEN_MODEL_PROFILE_NAME = "open_model.profile.json"
_MERKLE_NAME = "merkle.json"
_JOURNAL_NAME = "journal.json"
_REVISION_GUARD_MARKER = "KIR_DOCUMENT_REVISION_GUARD_V1"


_REVISION_FINGERPRINT_CS = r"""
Func<string> __KirDocumentRevision = () =>
{
    // Element.VersionGuid is present in the 2021-2026 API surfaces.  Two
    // independent 64-bit streams make this compact enough for every bridge
    // call while covering add/delete/modify (including type elements).
    ulong __h1 = 1469598103934665603UL;
    ulong __h2 = 1099511628211UL;
    long __count = 0L;
    // Revit refuses to iterate a collector that carries no filter at all
    // ("The collector does not have a filter applied"), which is exactly what
    // an unqualified `new FilteredElementCollector(doc)` is.  "Everything,
    // instances and types alike" therefore has to be SPELLED as a filter that
    // passes everything -- the two halves of ElementIsElementTypeFilter OR'd
    // together -- rather than as the absence of one.  Narrowing to instances
    // would be legal and wrong: a type rename is a modification the guard
    // exists to notice.
    var __everything = new LogicalOrFilter(
        new ElementIsElementTypeFilter(false),
        new ElementIsElementTypeFilter(true));
    var __all = new FilteredElementCollector(doc)
        .WherePasses(__everything).ToElements()
        .OrderBy(__e => long.Parse(__e.Id.ToString()));
    foreach (var __e in __all)
    {
        string __token = __e.Id.ToString() + ":" +
            __e.VersionGuid.ToString("N") + ";";
        unchecked
        {
            foreach (char __ch in __token)
            {
                __h1 ^= (ulong)__ch;
                __h1 *= 1099511628211UL;
                __h2 += (ulong)__ch;
                __h2 += (__h2 << 10);
                __h2 ^= (__h2 >> 6);
            }
        }
        __count++;
    }
    unchecked
    {
        __h2 += (__h2 << 3);
        __h2 ^= (__h2 >> 11);
        __h2 += (__h2 << 15);
    }
    return __count.ToString() + ":" + __h1.ToString("x16") +
        ":" + __h2.ToString("x16");
};
""".strip()


def _revision_guard_cs(code: str) -> str:
    """Wrap one read in before/after document-revision witnesses."""

    return "\n".join((
        f"// {_REVISION_GUARD_MARKER}",
        _REVISION_FINGERPRINT_CS,
        "string __kirRevisionBefore = __KirDocumentRevision();",
        "Func<object> __kirRevisionRead = () =>",
        "{",
        code,
        "};",
        "object __kirRevisionPayload = __kirRevisionRead();",
        "string __kirRevisionAfter = __KirDocumentRevision();",
        "return new Dictionary<string, object> {",
        '    {"revision_before", __kirRevisionBefore},',
        '    {"revision_after", __kirRevisionAfter},',
        '    {"payload", __kirRevisionPayload}',
        "};",
    ))


class _RevisionGuardedExecutor:
    """Bind every bridge read in one run to an exact revision fingerprint."""

    def __init__(
        self,
        executor: BridgeExecutor,
        *,
        expected: str | None = None,
        on_first: Callable[[str], None] | None = None,
    ) -> None:
        self._executor = executor
        self._revision = expected
        self._on_first = on_first

    @property
    def revision(self) -> str | None:
        return self._revision

    async def __call__(self, code: str, *, timeout_ms: int) -> Any:
        from kir.decompile.extract import _unwrap_bridge_payload

        raw = await self._executor(
            _revision_guard_cs(code), timeout_ms=timeout_ms)
        envelope = _unwrap_bridge_payload(raw)
        if not isinstance(envelope, Mapping):
            raise DocumentRevisionError(
                "revision-guard response is not an object")
        before = envelope.get("revision_before")
        after = envelope.get("revision_after")
        if not isinstance(before, str) or not before \
                or not isinstance(after, str) or not after:
            raise DocumentRevisionError(
                "revision-guard response lacks before/after fingerprints")
        if before != after:
            raise DocumentRevisionError(
                "document changed during one bridge read")
        if self._revision is None:
            self._revision = before
            if self._on_first is not None:
                self._on_first(before)
        elif before != self._revision:
            raise DocumentRevisionError(
                "document changed between bridge reads")
        if "payload" not in envelope:
            raise DocumentRevisionError(
                "revision-guard response lacks read payload")
        return envelope["payload"]


class PipelineError(RuntimeError):
    """A typed A1 failure.  Callers translate it into a serving dict."""

    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        d = {"code": self.code, "message": self.message}
        if self.detail:
            d["detail"] = self.detail[:400]
        return d


StatusCallback = Callable[[dict[str, Any]], None]

# A side-index C# builder takes an id sequence and returns one read-only body.
# curve/sketch/curtain/family_placement/group all ship builders in-repo now
# (Wave A1b added the family_placement/group emitters); a stage is only
# recorded as ``skipped_no_builder`` if a builder is explicitly absent (I2/I5).
SideCsBuilder = Callable[[Sequence[str]], str]


@dataclass(frozen=True, slots=True)
class DecompileRunResult:
    """Outcome of one live run.  ``ok=False`` carries a typed ``error``."""

    ok: bool
    out_dir: str
    change_stamp: str
    stages: tuple[str, ...]
    error: Optional[dict[str, Any]] = None
    passport_path: Optional[str] = None
    cancelled: bool = False
    slo_violations: int = 0
    elements_total: int = 0
    # §18.4: contamination marker. Whether the model was known to be read
    # incompletely (closed worksets) is a property of the RUN, not an L0
    # detail: anyone holding run.json in their hands must see it without
    # parsing the JSONL header.
    # 🔴 THIS FIELD'S DEFAULT COINCIDED WITH THE VALUE "ALL GOOD."
    # Measured 20.08.2026 on a real building: the run failed at the
    # `extract` stage (31 `partial` categories, 33 944 elements unread),
    # that is, BEFORE materialization, which is the only place the field
    # gets assigned. `status.json` shipped `is_partial_read: false` —
    # "read completely" — for a run that failed EXACTLY because of
    # incomplete reading.
    # A reader could not tell "measured and complete" from "never
    # measured at all": this house's version of the named form (a
    # quantity that wasn't counted prints as its most innocuous-looking
    # value). Below, the field stops being printed until it is measured;
    # consumers read it through `bool(...)`/truthiness, so a missing key
    # behaves exactly like the previous `false`, but no longer ASSERTS
    # anything.
    partial_read_measured: bool = False
    is_partial_read: bool = False
    worksets_closed: int = 0
    # §18.1: the law's four numbers are printed EXPLICITLY, not derived by
    # the reader. ``census`` is the summary of
    # decompile.census.CensusBalance.to_dict(); ops/atoms travel here too,
    # so that run.json carries the whole identity, not half of it filled
    # in from the passport.
    census: dict[str, Any] = field(default_factory=dict)
    ops_lifted: int = 0
    atoms: int = 0
    # §18.2: the aggregate of side-index receipts. It was assembled,
    # merged, saved — and read by NOBODY (M5 of the 28.07 audit): a wall
    # whose arc the budget cut was lifted as a chord and counted in the
    # statistics as a success. Here it is carried into the same file that
    # holds the percentages — so that reading the percentage without
    # seeing the cuts becomes impossible.
    side_failures: dict[str, Any] = field(default_factory=dict)
    # F-260/F-250: lift-cache entries the wrapper REFUSED to read — by
    # their REASONS. An empty list means "there were no refusals," not
    # "there's no one to ask": it is asked of
    # `lift_cache.lift_cache_refusals` AFTER the lift stage, that is, once
    # there is something to answer with.
    #
    # 🔴 WITHOUT THIS FIELD A CACHE REFUSAL WOULD REMAIN A `logger.debug`
    # GOING NOWHERE, and a dead guard is no different from a missing one.
    # An operator whose "hit" took the full lift time asks here and gets
    # the NAME OF THE REASON instead of a guess.
    lift_cache_refusals: list[str] = field(default_factory=list)
    # RUN DURATION. It was in NOT ONE of the 78 snapshots on disk:
    # run.json carried `elements_total`, the passport, and the revision
    # fingerprint — but how long it took had to be guessed from file
    # timestamps, and on a resume the guess gave 69 hours where the work
    # had taken one hour. I4 permits time in the run's metadata (it is
    # forbidden in deterministic artifacts — L0 and the programs), and it
    # lives exactly here.
    timing: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ok": self.ok,
            "timing": dict(self.timing),
            "out_dir": self.out_dir,
            "change_stamp": self.change_stamp,
            "stages": list(self.stages),
            "cancelled": self.cancelled,
            "slo_violations": self.slo_violations,
            "elements_total": self.elements_total,
            **({"is_partial_read": self.is_partial_read}
               if self.partial_read_measured else {}),
            "worksets_closed": self.worksets_closed,
            "ops_lifted": self.ops_lifted,
            "atoms": self.atoms,
            **dict(self.census),
            **dict(self.side_failures),
            "lift_cache_refusals": list(self.lift_cache_refusals),
        }
        if self.error is not None:
            d["error"] = self.error
        if self.passport_path is not None:
            d["passport_path"] = self.passport_path
        return d


@dataclass(slots=True)
class _RunState:
    """Mutable per-run bookkeeping mirrored into ``status.json`` atomically."""

    out_dir: Path
    change_stamp: str
    stage: str = "init"
    batch: int = 0
    done: int = 0
    total: int = 0
    errors: list[str] = field(default_factory=list)
    slo_violations: int = 0
    stages_done: list[str] = field(default_factory=list)
    elements_total: int = 0
    # §18.4: status is the first thing the operator sees during a run;
    # incomplete reading must be visible BEFORE the passport with
    # percentages appears.
    # 🔴 THIS FIELD'S DEFAULT COINCIDED WITH THE VALUE "ALL GOOD."
    # Measured 20.08.2026 on a real building: the run failed at the
    # `extract` stage (31 `partial` categories, 33 944 elements unread),
    # that is, BEFORE materialization, which is the only place the field
    # gets assigned. `status.json` shipped `is_partial_read: false` —
    # "read completely" — for a run that failed EXACTLY because of
    # incomplete reading.
    # A reader could not tell "measured and complete" from "never
    # measured at all": this house's version of the named form (a
    # quantity that wasn't counted prints as its most innocuous-looking
    # value). Below, the field stops being printed until it is measured;
    # consumers read it through `bool(...)`/truthiness, so a missing key
    # behaves exactly like the previous `false`, but no longer ASSERTS
    # anything.
    partial_read_measured: bool = False
    is_partial_read: bool = False
    worksets_closed: int = 0
    # §18.1: what wasn't read is visible DURING the run, not only in the
    # passport afterward — for the same reason the partial-read marker
    # ended up there too.
    census: dict[str, Any] = field(default_factory=dict)
    # §18.2: the cuts are visible DURING the run, not only in the passport
    # afterward — for the same reason the partial-read marker ended up
    # there too.
    side_failures: dict[str, Any] = field(default_factory=dict)
    # F-260/F-250: lift-cache entries the wrapper REFUSED to read — by
    # their REASONS. An empty list means "there were no refusals," not
    # "there's no one to ask": it is asked of
    # `lift_cache.lift_cache_refusals` AFTER the lift stage, that is, once
    # there is something to answer with.
    #
    # 🔴 WITHOUT THIS FIELD A CACHE REFUSAL WOULD REMAIN A `logger.debug`
    # GOING NOWHERE, and a dead guard is no different from a missing one.
    # An operator whose "hit" took the full lift time asks here and gets
    # the NAME OF THE REASON instead of a guess.
    lift_cache_refusals: list[str] = field(default_factory=list)
    # ── TIMING INSTRUMENT ───────────────────────────────────────────────
    # Stage duration in ms, keyed by stage name. Written UPON COMPLETION
    # of a stage, so a stage in progress is absent from the dict, not
    # zero: "still running" and "finished instantly" must be
    # distinguishable.
    stage_ms: dict[str, float] = field(default_factory=dict)
    # Per-category/per-stage breakdown of the bridge and our own side —
    # see extract._TIMING_KEYS for where the measurement boundary runs.
    timing_extract: dict[str, Any] = field(default_factory=dict)
    timing_sides: dict[str, Any] = field(default_factory=dict)
    #: A monotonic timestamp of the run's start; it carries no wall-clock time.
    started_at: float = field(default_factory=time.monotonic)

    def timing_dict(self) -> dict[str, Any]:
        """Assemble the ``timing`` section for status.json/run.json.

        THE BOUNDARY IS DECLARED RIGHT HERE, IN THE ARTIFACT ITSELF
        (`boundary`), not only in a report: an instrument whose coverage
        is known only to its author is an instrument for part of the
        range, and a reader has every right to mistake it for the whole.
        """

        return {
            "schema": 1,
            "elapsed_ms": round(
                (time.monotonic() - self.started_at) * 1000.0, 1),
            "stage_ms": {k: round(v, 1) for k, v in self.stage_ms.items()},
            "extract": dict(self.timing_extract),
            "sides": dict(self.timing_sides),
            "boundary": (
                "bridge_ms = вебсокет + UI-поток Revit + Roslyn + коллектор + "
                "сериализация в плагине; ИЗ ПИТОНА НЕ ДЕЛИТСЯ (плагин своего "
                "времени не возвращает). parse_ms/write_ms — наша сторона. "
                "probe_ms/pages — верхняя оценка постоянной цены вызова."
            ),
        }

    def status_dict(self) -> dict[str, Any]:
        # No wall-clock in the deterministic artifacts; status carries a single
        # ``updated_at`` metadata stamp only (I4 exempts status/run metadata).
        return {
            "stage": self.stage,
            "batch": self.batch,
            "done": self.done,
            "total": self.total,
            "errors": list(self.errors[:20]),
            "cancel_requested": _read_cancel(self.out_dir),
            "slo_violations": self.slo_violations,
            "stages_done": list(self.stages_done),
            "elements_total": self.elements_total,
            **({"is_partial_read": self.is_partial_read}
               if self.partial_read_measured else {}),
            "worksets_closed": self.worksets_closed,
            **dict(self.census),
            **dict(self.side_failures),
            "lift_cache_refusals": list(self.lift_cache_refusals),
            # Duration is visible DURING the run, not only in run.json
            # afterward: "how long has it been running and where did the
            # time go" is the operator's first question at the fortieth
            # minute, and we've already tried answering it with file
            # size.
            "timing": self.timing_dict(),
            "updated_at": time.time(),
        }


# ── atomic JSON persistence (mirrors extract._atomic_write_json) ─────────────
#: A counter distinguishing two consecutive saves from the SAME thread.
#: `itertools.count`'s `next()` is a single C-level call, so it needs no
#: separate lock.
_TMP_SEQ = itertools.count()


def _tmp_path_for(path: Path) -> Path:
    """A temporary file name, OWN TO EACH WRITER.

    Three discriminators, and each closes off its own kind of collision:
    `pid` covers a different PROCESS (the pipeline and a cancellation are
    different processes when cancelled over HTTP), the counter covers a
    neighboring write from the same thread, a random tail covers
    everything else (thread ids are reused, and so is pid).
    """

    return path.with_name(
        f"{path.name}.{os.getpid()}.{next(_TMP_SEQ)}."
        f"{os.urandom(4).hex()}.tmp")


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    """Replace `path` wholly: it is either the old one or the new one, no third state.

    🔴 THE TEMP FILE NAME IS UNIQUE, NOT FIXED (F-070/RH-12). The
    previous `<name>.tmp` was ONE FOR ALL WRITERS into the directory, and
    `status.json` is written concurrently by the run's progress
    (`_write_status`), by a cancellation (`request_cancel`), and by the
    bridge from `serving.py`. Measured with 2×1000 writes into one
    `status.json`: **423 exceptions** of `FileNotFoundError:
    status.json.tmp -> status.json` — one writer's `os.replace` snatched
    another's temp file out from under it. After a unique name, on the
    same experiment — 0. The same class of bug already closed in
    `model/snapshot_io.py` (E-14).

    A unique name removes the FILE COLLISION and does not remove a lost
    write: `request_cancel`'s "read-add-replace" is still without a lock,
    and the last writer wins. For `status.json` this is legitimate (the
    cancellation flag is reread from disk in `status_dict`); for the
    building journal it is not, and there an inter-process lock stands
    (`journal_store._log_lock`).

    The permissions stay the same as the previous `open("wb")` gave:
    `O_CREAT` with 0o666 is masked by the process's umask exactly the
    same way. `tempfile.mkstemp` would have given 0o600 and silently
    narrowed access for a status reader running under a different user.
    """

    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    tmp = _tmp_path_for(path)
    # O_EXCL: a residual name collision must be LOUD, not a quiet write
    # into someone else's file.
    descriptor = os.open(
        str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        # NO GARBAGE ACCUMULATES. A unique name means a failed write
        # would leave behind a file that nothing will ever overwrite
        # again: with the previous fixed name, the next write erased it
        # on its own.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        with path.open("rb") as handle:
            value = json.loads(handle.read())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _read_cancel(out_dir: Path) -> bool:
    status = _read_json(out_dir / _STATUS_NAME)
    return bool(status and status.get("cancel_requested") is True)


async def _offload(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """A heavy SYNCHRONOUS step is run off the event-loop thread.

    THE LIVE MEASUREMENT ON 30.07 that caused this. During a tower
    extraction, ``/health`` failed to respond twelve times in a row, 25
    seconds each — while a minute earlier it had answered in 2 ms. The
    backend runs on a SINGLE worker (``uvicorn --workers 1``), and while
    the pipeline materialized 88 MB of L0, parsed 18 MB of side index,
    lifted, folded, and serialized the passport, the server answered
    NOBODY: chat sockets got no reply to their ping and dropped with
    ``close_code=1006`` (62 drops in 12 hours across ten different
    devices), HTTP hung. The complaint sounded like "every so often the
    server just falls off"; in reality it happened every single time
    someone ran a decompile.

    What this gives, and what it does NOT give. The step remains
    CPU-bound Python and holds the GIL, so the thread does NOT speed up
    the decompile or compute in parallel. It gives exactly one thing: the
    interpreter releases the GIL every few milliseconds
    (``sys.setswitchinterval``), the event loop gets control, and manages
    to answer the ping. The goal is RESPONSIVENESS, not throughput, and
    the two must not be confused.

    The executor belongs to ONE step. This is not cosmetic: on some
    supported Python/runtime boundaries a finished worker's callback does
    not wake the selector event loop; ``run_in_executor`` then waits
    forever for a result that is already ready. The pipeline has several
    sequential offloads, so this turns a successful step into a hung run
    with no typed outcome. We poll the concurrent future with a short
    async timer: the event loop stays responsive, and correctness doesn't
    depend on a cross-thread wakeup. A single-task executor also gives
    each transition its own lifecycle; on cancellation ``wait=False``
    doesn't block the event loop, and a finished worker shuts down
    synchronously.
    """
    executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="kir-decompile-offload",
    )
    # submit + timer polling intentionally avoids cross-thread loop callbacks.
    future = executor.submit(partial(func, *args, **kwargs))
    try:
        while not future.done():
            await asyncio.sleep(0.01)
        return future.result()
    finally:
        completed = future.done()
        if not completed:
            future.cancel()
        executor.shutdown(wait=completed, cancel_futures=True)


class _stage_clock:
    """Measure one stage and record its duration into the state.

    Records even on an exception: a stage that failed at the fortieth
    minute cost forty minutes, and losing that means losing the run's
    most expensive measurement. Re-entering the same stage (a resume, a
    retry) ACCUMULATES — the key holds the work, not the last attempt.
    """

    __slots__ = ("state", "name", "_t0")

    def __init__(self, state: _RunState, name: str) -> None:
        self.state = state
        self.name = name

    def __enter__(self) -> "_stage_clock":
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *exc: Any) -> None:
        elapsed = (time.monotonic() - self._t0) * 1000.0
        self.state.stage_ms[self.name] = (
            self.state.stage_ms.get(self.name, 0.0) + elapsed)
        return None


async def _timed(state: _RunState, name: str, coro: Awaitable[Any]) -> Any:
    """Wraps a clock around an ALREADY-created coroutine — a wrapper without moving code.

    Needed where the stage is one multi-line expression (the tail's
    ``_offload``): a ``with`` would require re-indenting the whole call,
    and the diff must stay readable. Time is recorded on an exception
    too: a lift that failed cost just as much as one that succeeded.
    """

    t0 = time.monotonic()
    try:
        return await coro
    finally:
        state.stage_ms[name] = (
            state.stage_ms.get(name, 0.0)
            + (time.monotonic() - t0) * 1000.0)


def _write_status(state: _RunState, status_cb: Optional[StatusCallback]) -> None:
    # Preserve an already-set cancel flag: status_dict() re-reads it from disk,
    # so writing back never clobbers a concurrently-set cancel request.
    payload = state.status_dict()
    _atomic_write_json(state.out_dir / _STATUS_NAME, payload)
    if status_cb is not None:
        try:
            status_cb(payload)
        except Exception:  # noqa: BLE001 — a progress sink must never abort a run
            pass


def request_cancel(out_dir: str | os.PathLike[str]) -> bool:
    """Set ``cancel_requested`` in ``status.json``; return True if a status exists."""
    directory = Path(out_dir)
    status = _read_json(directory / _STATUS_NAME)
    if status is None:
        return False
    status["cancel_requested"] = True
    status["updated_at"] = time.time()
    _atomic_write_json(directory / _STATUS_NAME, status)
    return True


def read_status(out_dir: str | os.PathLike[str]) -> Optional[dict[str, Any]]:
    """Return the persisted ``status.json`` (or None if the run never started)."""
    return _read_json(Path(out_dir) / _STATUS_NAME)


# ── probe protocol (Д2) ──────────────────────────────────────────────────────
Probe = tuple[int, tuple[tuple[str, int], ...]]


async def _probe(
    executor: BridgeExecutor,
    category: str,
    *,
    timeout_ms: int,
    link_title: str | None = None,
) -> Probe:
    """Return ``(count, level_fingerprint)`` for one category via one bridge call.

    Reuses ``build_category_probe_cs`` (count + per-level scope).  The
    deterministic ``(count, sorted level (key,count) tuple)`` fingerprint
    changes whenever the model is edited between probes.  Returns
    ``(-1, ())`` on any bridge failure (treated as unknown, never a silent
    zero).

    The probe must count the SAME document as the stage it guards. A
    host-based probe wrapped around a stage that reads a link is not a
    false positive but a GUARD WITH NO SUBJECT: it will agree with itself
    through any edit inside the link, and "the model hasn't changed" will
    turn out to be a claim about a different document.
    """
    from kir.decompile.extract import _execute_with_retries, _parse_probe
    try:
        payload = await _execute_with_retries(
            executor,
            build_category_probe_cs(category, link_title=link_title),
            timeout_ms=timeout_ms, retries=0)
        count, scopes = _parse_probe(payload)
    except Exception:  # noqa: BLE001 — unknown probe, not a silent zero
        return (-1, ())
    fingerprint = tuple(sorted((s.key, s.count) for s in scopes))
    return (count, fingerprint)


async def _probe_categories(
    executor: BridgeExecutor,
    categories: Sequence[str],
    *,
    timeout_ms: int,
    link_title: str | None = None,
) -> dict[str, Probe]:
    result: dict[str, Probe] = {}
    for category in categories:
        result[category] = await _probe(
            executor, category, timeout_ms=timeout_ms, link_title=link_title)
        await asyncio.sleep(_YIELD_S)
    return result


def _probes_agree(
    before: Mapping[str, Probe],
    after: Mapping[str, Probe],
) -> bool:
    for category, value in before.items():
        other = after.get(category)
        if other is None:
            return False
        # An unknown probe (-1) on either side cannot prove agreement.
        if value[0] < 0 or other[0] < 0 or value != other:
            return False
    return True


# ── side-index stage runner ──────────────────────────────────────────────────
def _default_cs_builders(
    revit_version: Any = None,
    link_title: str | None = None,
) -> dict[str, SideCsBuilder]:
    """Builders that ship with a verified in-repo bridge collector.

    ``link_title`` — WHOSE document all the stages read at once. It lives
    here, not in every call, for exactly the reason the stages got it in
    the first place: one snapshot — one document, and a stage forgotten
    during distribution would silently read the host (measured 30.07:
    1837 receipts for one stage, and 20 foreign rows in that very same
    one).

    ``group`` takes no ids (a Revit group is not an extracted L0 category, so
    there is no id list to page over); its collector is whole-model but
    internally bounded, and the adapter ignores the id list.  Every other
    stage — ``curve`` / ``curtain`` / ``sketch`` / ``family_placement`` —
    pages over the requested L0 id list.

    ``sketch`` joined the paged stages in the §18.2 wave: it was the last
    whole-model reader without a budget (three full-document passes in one
    30-second call with ``retries=0``), which is a coin toss on any building
    larger than the one it was written against.
    """
    return {
        "curve": lambda ids: build_curve_extract_cs(
            list(ids), link_title=link_title),
        "curtain": lambda ids: build_curtain_extract_cs(
            list(ids), link_title=link_title),
        "sketch": lambda ids: build_sketch_extract_cs(
            list(ids), link_title=link_title),
        "family_placement":
            lambda ids: build_family_placement_extract_cs(
                list(ids), link_title=link_title),
        "group": lambda _ids: build_group_extract_cs(link_title=link_title),
        # Annotation is a paged stage on par with the others: 13 905
        # dimensions and 2 697 notes in one whole-model pull would be the
        # same coin toss that moved sketch into the paged stages.
        "annotation": lambda ids: build_annotation_extract_cs(
            list(ids), link_title=link_title),
        # System membership: without it an engineering building can't be
        # rebuilt (a dry run on Snowdon, 30.07 — 0/26 chunks).
        "mep_system": lambda ids: build_mep_system_extract_cs(
            list(ids), link_title=link_title),
        # JOINS. The owner extracted the building and reassembled it:
        # "walls everywhere overlap each other and nothing is joined to
        # anything else." The forward pass didn't lose the joins — they
        # were NEVER read: before 18.08, ``GetJoinedElements`` appeared 0
        # times in this package.
        #
        # THE COST IS A LIVE MEASUREMENT, and the provenance is complete,
        # because without it the number cannot be cited (Form 26):
        # 18.08.2026 · Revit 2023 · document `13A-RD-AR-K2_v33`, 15 930
        # walls · ids taken from `query_list`, not invented · the body
        # assembled by this very ``build_join_extract_cs``:
        #
        #      20 ids -> 304 ms, response  1 900 B,  9 joined, 16 pairs
        #     200 ids -> 332 ms, response 17 678 B, 55 joined, 99 pairs
        #
        # The cost is FLAT: a tenfold increase in id count costs 28 ms —
        # what's paid for is traversing the document, not the elements.
        # For comparison, the cheapest phase of a live run
        # (``acceptance_before``) costs 1 220 ms, that is, the stage is
        # three times cheaper than it.
        #
        # 🔴 THE MOCK GAVE 25 626.7 ms — 77 TIMES MORE, and this was a
        # property of the mock (it didn't know the stage and fell into a
        # retry with a timeout), not of the stage. Fixed in
        # ``tests/test_pipeline._join_payload``; raising the budget would
        # have been cheaper and would have hidden the next real
        # regression.
        "join": lambda ids: build_join_extract_cs(
            list(ids), link_title=link_title),
        # TAGS — the ONLY stage whose C# DEPENDS ON THE Revit VERSION. A
        # tag's target has no single member alive across all six versions
        # (TaggedLocalElementId removed after 2022, GetTaggedLocalElementIds
        # absent in 2021), so the version arrives here from the document
        # being read (``Application.VersionNumber``) rather than being
        # guessed. The argument is optional for exactly the reason that a
        # call without it — and one exists in the contract tests — must
        # still enumerate the stages.
        "dimension": lambda ids: build_dimension_extract_cs(
            list(ids), link_title=link_title),
        "tag": lambda ids: build_tag_extract_cs(
            list(ids), revit_version=revit_version, link_title=link_title),
        # Tier G is dynamic: unlike the semantic side indexes, it receives
        # only the ids that remained honest atoms after LIFT.  Registration
        # still lives here so source binding and the six-version gate cannot
        # drift from the body shipped by the live pipeline.
        "geometry": lambda ids: build_geometry_extract_cs(
            list(ids), link_title=link_title),
    }


# Which L0 categories feed each side-index stage (I1 — data-driven, no LOT31).
# ``group`` has no L0 category (a group is not an extracted category); its
# collector picks group instances itself, so it is a whole-model stage.
_STAGE_CATEGORIES: dict[str, frozenset[str]] = {
    "curve": frozenset({"OST_Walls", "OST_StructuralFraming"}),
    # Ceilings and railings were added on 29.07 in the CAPTURE wave. The
    # trigger isn't that the operations appeared (they arrived a day
    # earlier), but that the operations had NOTHING TO FEED ON: on K2 all
    # 81 ceilings and all 203 railings sat as bbox_only with empty params
    # and appeared in NOT A SINGLE side index.
    #
    # The row and the collectors in sketch_extract.py must move
    # TOGETHER: a category here without a collector there ⇒ every id
    # leaves as an `element_not_claimed` receipt (class CUT) and inflates
    # the cut for no reason; THIS COMMENT GUESSED THE DEFECT AND DID NOT
    # STOP IT (measured 12.08.2026): `OST_StairsRailing` sits lower in
    # the set, the collector picks up only part of its elements, and 172
    # of 173 receipts in the overall catch on `k2_ar_rd_v7` are exactly
    # it. The prose turned out to be right and just sat there: "write it
    # down in prose" is our staircase's lowest-grade remedy, and this is
    # its cost. Before 12.08 the catch sent `element_unresolved`, that
    # is, it claimed elements found in L0, all 173 of 173, were ABSENT
    # FROM THE DOCUMENT;
    # a collector there without a row here ⇒ ids are never requested,
    # __skAccept cuts them off, and the stage silently reads nothing.
    "sketch": frozenset({
        "OST_Floors", "OST_Roofs", "OST_Stairs",
        "OST_Ceilings", "OST_StairsRailing", "OST_Railings",
    }),
    # There are three kinds of curtain-grid host (wall, curtain system,
    # roof). OST_CurtaSystem was added to extract.py's category table
    # (the tail of the aaa44b45 wave, 28.07) — now all three kinds are
    # here too, and the pipeline feeds their stage ids on par with the
    # wall and the roof.
    "curtain": frozenset({"OST_Walls", "OST_Roofs", "OST_CurtaSystem"}),
    # Annotation categories are held by THEIR OWN module
    # (annotation_extract), not the list here: a row in the table and a
    # collector in the reader must travel as a pair, and the only way to
    # guarantee that is a single source.
    "annotation": ANNOTATION_CATEGORIES,
    "mep_system": MEP_SYSTEM_CATEGORIES,
    # Joinable categories are held by THEIR OWN module (join_extract) for
    # the same reason as tags, dimensions, and annotation: a row in this
    # table and a collector in the reader must travel as a pair, and the
    # only way to guarantee that is a single source.
    "join": JOIN_CATEGORIES,
    # The ten kinds of tags are held by THEIR OWN module (tag_extract)
    # for the same reason as annotation: a row in the table and a
    # collector in the reader must travel as a pair, and the only way to
    # guarantee that is a single source.
    "tag": TAG_CATEGORIES,
    # Dimensions are held by THEIR OWN module (dimension_extract) for the
    # same reason as tags and annotation: a row in the table and a
    # collector in the reader must travel as a pair, and the only way to
    # guarantee that is a single source.
    "dimension": DIMENSION_CATEGORIES,
    # Categories whose elements are FAMILY INSTANCES. Without a row in
    # the side index, such an element never lifts at all: the lift
    # learns from it the placement kind, the point, the curve, and the
    # flips.
    #
    # MEASURED 28.07: once the extractor learned to see sections, ЭОМ
    # gave 2546 elements instead of 1916 — and 354 of the new ones became
    # atoms with the one reason «element is absent from the family
    # placement side index». The category was added to reading but not
    # to the index: the section became VISIBLE but still inexpressible.
    #
    # The index is closed by construction (it produces no rows for
    # non-FamilyInstance), so an extra category here is harmless, while
    # a missing one silently loses elements.
    "family_placement": frozenset({
        "OST_Doors", "OST_Windows", "OST_Columns", "OST_StructuralColumns",
        "OST_StructuralFraming", "OST_StructuralFoundation", "OST_Furniture",
        "OST_GenericModel",
        # ЭОМ
        "OST_ElectricalEquipment", "OST_ElectricalFixtures",
        "OST_LightingFixtures", "OST_LightingDevices",
        "OST_CableTrayFitting", "OST_ConduitFitting",
        # ОВ
        "OST_MechanicalEquipment", "OST_DuctFitting", "OST_DuctTerminal",
        # ВК
        "OST_PlumbingFixtures", "OST_PipeFitting", "OST_PipeAccessory",
        "OST_Sprinklers",
        # КР
        "OST_StructuralTruss",
        # АР
        "OST_Casework", "OST_SpecialityEquipment",
        "OST_CurtainWallPanels", "OST_CurtainWallMullions",
        # РД, 29.07: the same trap described above, caught BEFORE it
        # cost elements. The reading-table expansion wave (54 → 73
        # categories) added to extract.py two kinds whose elements are
        # family instances: node elements and telephone devices
        # (measured on 13A-RD-AR-K2_v33: 3046 + 4479 = 7525 units).
        # Without a row here they would have become visible to reading
        # and inexpressible by the lift — exactly the «absent from the
        # family placement side index» that ЭОМ paid for on 28.07.
        "OST_DetailComponents", "OST_TelephoneDevices",
        # SYSTEM CATEGORIES THAT HOLD FAMILY INSTANCES (22.08.2026). Both
        # are taken NOT WHOLLY — see `_STAGE_CATEGORY_SHAPES` below:
        # without a discriminator, `OST_Walls` would bring in 7 845 real
        # walls, that is, 7 845 definition-refusals and two extra
        # round-trips on the bridge.
        "OST_Walls", "OST_StairsRailing",
    }),
    "group": frozenset(),
}

#: THE GEOMETRY SHAPE THE STAGE TAKES FROM THE SYSTEM CATEGORY.
#:
#: WHY THIS TABLE. Category and CLASS are different things, and a
#: project's author has every right to place a family instance into a
#: system element's category. Before 22.08.2026 the reader asked BY
#: CATEGORY while the collector filtered BY CLASS, and the difference
#: was thrown away — under three different words in three stages:
#:
#:     2 801  OST_Walls          curtain: element_kind_mismatch, class not named
#:                               family_placement: didn't ask AT ALL
#:     1 114  OST_StairsRailing  sketches: element_not_claimed
#:
#: THE DISCRIMINATOR IS MECHANICAL, NOT BY TYPE NAME. ``geom_kind`` is
#: derived directly from ``Element.Location`` (`geometry_store.py:104-147`):
#: ``LocationCurve`` -> ``curve``, ``LocationPoint`` -> ``point``,
#: otherwise ``bbox_only``. A real wall ALWAYS has an axis; a family
#: instance has a point. The MNVNK K6 measurement separates them with no
#: remainder:
#:
#:     OST_Walls          10 646 = 7 845 curve (all with WALL_*) + 2 801 point (none)
#:     OST_StairsRailing   1 216 =   102 bbox_only (a real Railing) + 1 114 point
#:
#: and 1 114 of the 1 115 ``element_not_claimed`` in the sketch stage are
#: EXACTLY those point-railings, while all 102 bbox_only ones sit in
#: ``railing_path_index``.
#:
#: 🔴 THE CONDITION IS SUFFICIENT, NOT COMPLETE, and this is said out
#: loud. ``point`` in the walls category CANNOT be a wall — the
#: inference is strict in this direction. It doesn't work the other way:
#: a family instance on a curve would arrive as ``curve`` and stay where
#: it already was. There are zero such on K6, but a measured zero is not
#: a zero of nature, so the stage's receipt remains a second carrier: a
#: skipped class must still name itself (`curtain_extract.py`, «not a
#: curtain host: <class>»), rather than vanish.
#:
#: Keeping the table in sync with the measurement is held by
#: `test_stage_category_shapes.py`, not by this comment.
_STAGE_CATEGORY_SHAPES: dict[tuple[str, str], bool] = {
    # The placement stage takes ONLY point-shaped elements from system
    # categories — those are exactly the family instances the category
    # was added here for.
    ("family_placement", "OST_Walls"): True,
    ("family_placement", "OST_StairsRailing"): True,
    # The sketch stage is exactly the opposite: its collector takes
    # `.OfType<Railing>()`, and point-shaped elements for it are not
    # "coverage oversight" (`element_not_claimed`, a CUT) but a foreign
    # class. Not asking for them is more honest than recording 1 114
    # cuts for work this stage doesn't have.
    ("sketch", "OST_StairsRailing"): False,
    ("sketch", "OST_Railings"): False,
}

# Stages whose request set is produced by an earlier compiler stage rather
# than selected from a static L0 category table.
_DYNAMIC_STAGE_IDS = frozenset({"geometry"})


def _ids_for_stage(document: L0Document, stage: str) -> list[str]:
    """Select L0 element ids for one side-index stage (I1 — data-driven).

    Category selects the element; ``_STAGE_CATEGORY_SHAPES`` additionally
    selects the SHAPE where two classes live in one category.
    """
    selection = _STAGE_CATEGORIES.get(stage)
    if not selection:
        return []
    out: list[str] = []
    for element in document.elements:
        if element.category not in selection:
            continue
        wants_point = _STAGE_CATEGORY_SHAPES.get((stage, element.category))
        if wants_point is not None:
            is_point = element.geom_kind is GeometryKind.POINT
            if is_point is not wants_point:
                continue
        out.append(element.element_id)
    return out


def _probe_cats_for_stage(document: L0Document, stage: str) -> list[str]:
    """Categories to probe for concurrent edits around a stage (Д2).

    Only categories actually present in L0 are probed (an absent category has
    nothing to diverge).  ``group`` has no L0 category, so it probes nothing.
    """
    wanted = _STAGE_CATEGORIES.get(stage) or frozenset()
    present = {e.category for e in document.elements}
    return sorted(wanted & present)


def _batched(ids: Sequence[str], size: int) -> list[list[str]]:
    return [list(ids[i:i + size]) for i in range(0, len(ids), size)]


def _geometry_atom_ids(l1_nodes: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return the exact Tier-G request set: honest, non-generated atoms."""

    result: list[str] = []
    for node in l1_nodes:
        if node.get("kind") != "atom":
            continue
        reason = node.get("reason")
        if isinstance(reason, Mapping) \
                and reason.get("code") == "generator_child":
            # The semantic parent regenerates this element.  Escrowing the
            # child as independent geometry would duplicate it on rebuild.
            continue
        source_id = node.get("source_element_id")
        if not isinstance(source_id, str) or not source_id:
            raise SideStageContractError(
                "geometry: atom has no source_element_id")
        result.append(source_id)
    if len(result) != len(set(result)):
        raise SideStageContractError(
            "geometry: atom source_element_id values must be unique")
    return result


def _generator_child_ids(l1_nodes: Sequence[Mapping[str, Any]]) -> list[str]:
    """Addresses of atoms that a semantic parent RECREATES.

    The ONLY `Authority.DERIVED_BY_REVIT` witness that exists in the data
    today, and it is EXPLICIT. A category table isn't fed here and can't
    be: a prior doesn't know who creates the element — that was exactly
    the ground the retracted claim about 14 713 fittings stood on.

    A complement to `_geometry_atom_ids`: that function SUBTRACTS these
    same children, and both lists must read one field, not two similar
    ones.
    """
    result: list[str] = []
    for node in l1_nodes:
        if node.get("kind") != "atom":
            continue
        reason = node.get("reason")
        if not isinstance(reason, Mapping) \
                or reason.get("code") != "generator_child":
            continue
        source_id = node.get("source_element_id")
        if isinstance(source_id, str) and source_id:
            result.append(source_id)
    return result


def _build_and_write_graph(
    directory: Path,
    l1_nodes: Sequence[Mapping[str, Any]],
    family_index: Mapping[str, Mapping[str, Any]],
    joins: Any,
) -> dict[str, Any]:
    """Assemble the building graph from a FRESH decompile and place it alongside. The fold is backward.

    Built from RAW L0 on disk, not from an in-memory `L0Document`: this
    is what `graph_from_l0`'s input demands ("header + element rows"),
    and this is also what makes the stage reproducible offline —
    `build_graph_for_run` on the same directory gives the same graph
    without Revit.
    """
    host_classes = {
        element_id: row["host_class"]
        for element_id, row in (family_index or {}).items()
        if isinstance(row, Mapping) and row.get("host_class")
    }
    graph = build_graph_for_run(
        directory,
        generator_child_ids=_generator_child_ids(l1_nodes),
        host_classes=host_classes,
        joins=(joins.join_index if joins is not None else None),
        # Predicate B is computed from this same L0; without it the
        # `opening_point_touches_room` kind goes dark and lands in
        # `sources_absent`. The cost is measured on MNVNK (33 944
        # elements): +0.87 s on top of 2.16 s and +1 223 edges, of which
        # 107 are proven pairs and 1 116 are named refutations. More
        # expensive than silence — but silence here would have cost a
        # whole kind.
        room_adjacency=True,
    )
    write_graph(directory, graph)
    census = graph.census
    return {
        "artifact": GRAPH_ARTIFACT_NAME,
        "nodes": len(graph),
        "edges": len(graph.edges),
        "relations": dict(graph.relation_counts()),
        "modalities": dict(graph.modality_counts()),
        "refused_nodes": dict(census.refusals),
        "sources_absent": list(census.sources_absent),
        "identity_authoritative_nodes": census.identity_authoritative_nodes,
        "identity_gaps": dict(census.identity_gaps),
    }


async def _run_side_stage(
    executor: BridgeExecutor,
    document: L0Document,
    stage: str,
    parse: Callable[[Any], Any],
    merge: Callable[[list[Any]], Any],
    cs_builders: Mapping[str, SideCsBuilder],
    state: _RunState,
    status_cb: Optional[StatusCallback],
    *,
    timeout_ms: int,
    whole_model: bool = False,
    window_budget: Any = None,
    link_title: str | None = None,
    requested_ids: Sequence[str] | None = None,
    probe_categories: Sequence[str] | None = None,
) -> tuple[Optional[Any], bool]:
    """Run one paginated side-index stage.  Returns ``(extraction, skipped)``.

    ``skipped`` is True when no builder is registered — an honest no-op, not a
    failure.  Probe agreement (Д2) is checked before and after; on divergence
    the stage is retried once, then a typed refusal is raised (I2).
    """
    from kir.decompile.extract import (
        EXTRACT_RETRIES, _WindowWaitBudget, _execute_awaiting_window)

    # Side stages called the bridge WITHOUT retries and without waiting
    # for the window (`retries=0`), and the very first network hiccup
    # killed them: measured 29.07 on K2 РД — the curve stage died with
    # «after 1 attempts: TimeoutError» right after extracting 55 293
    # elements, while Revit's UI thread hadn't caught its breath yet.
    # The category-paging discipline (#26) extends here without
    # exception: reads are idempotent, each guarded by a revision.
    if window_budget is None:
        window_budget = _WindowWaitBudget()

    builder = cs_builders.get(stage)
    if builder is None:
        state.errors.append(f"{stage}: skipped_no_builder")
        return None, True

    ids = (
        list(requested_ids)
        if requested_ids is not None else _ids_for_stage(document, stage))
    if len(ids) != len(set(ids)):
        raise SideStageContractError(
            f"{stage}: requested element ids must be unique")
    if not ids and not whole_model:
        return merge([]), False

    # Categories to probe for concurrent edits around this stage (Д2).  Uses
    # the stage's own L0 categories — for whole-model stages too — never a
    # wall proxy.
    probe_cats = (
        sorted(set(probe_categories))
        if probe_categories is not None
        else _probe_cats_for_stage(document, stage))

    async def _drive() -> Any:
        payloads: list[Any] = []
        # Whole-model stages (sketch, group) ship a builder that ignores the id
        # list and reads the entire document in ONE call, so they must run as a
        # single batch.  Paging them by ``ids`` (when their L0 categories exceed
        # _SIDE_BATCH) re-runs the same whole-model extraction per batch, and
        # ``_merge_*`` concatenates the identical records → a duplicate
        # element_id that trips the side-index post-init (surfaced live on a
        # >200-floor/roof/stairs building; latent when the count was ≤ one page).
        if whole_model:
            batches: list[list[str]] = [[]]
        else:
            batches = _batched(ids, _SIDE_BATCH) if ids else [[]]
        state.total = len(batches)
        for index, batch in enumerate(batches):
            if _read_cancel(state.out_dir):
                raise PipelineError("cancelled", "cancel requested between batches")
            state.batch = index
            code = builder(batch)
            t0 = time.monotonic()
            payload = await _execute_awaiting_window(
                executor, code, timeout_ms=timeout_ms,
                retries=EXTRACT_RETRIES, budget=window_budget,
                what=f"боковая стадия {stage} пачка {index + 1}/{len(batches)}")
            t1 = time.monotonic()
            # THE VIOLATION COUNTER WAS ALREADY MEASURING THIS TIME AND
            # THROWING IT AWAY. `slo_violations` counted threshold
            # crossings and lost the duration itself: "three violations"
            # is indistinguishable from "three times 21 seconds" and
            # from "three times nine minutes." The same measurement, the
            # same cost — now it's also kept.
            if (t1 - t0) * 1000.0 > _SLO_CALL_MS:
                state.slo_violations += 1
            part = parse(payload)
            slot = state.timing_sides.setdefault(
                stage, {"bridge_ms": 0.0, "parse_ms": 0.0, "batches": 0})
            slot["bridge_ms"] = round(
                slot["bridge_ms"] + (t1 - t0) * 1000.0, 3)
            slot["parse_ms"] = round(
                slot["parse_ms"] + (time.monotonic() - t1) * 1000.0, 3)
            slot["batches"] += 1
            # §18.2: the stage checks REQUESTED against RECEIVED right
            # here, on its own batch — a lost id is named by its
            # address, rather than surfacing two stages later as a hole
            # in coverage. Whole-model stages (group) don't place an
            # order, there's nothing to check there.
            if batch:
                _reconcile_side_stage(
                    stage, requested=batch, accounted=_accounted_ids(part))
            payloads.append(part)
            state.done = index + 1
            _write_status(state, status_cb)
            await asyncio.sleep(_YIELD_S)
        return merge(payloads)

    state.stage = stage
    _write_status(state, status_cb)

    with _stage_clock(state, stage):
        before = await _probe_categories(
            executor, probe_cats, timeout_ms=timeout_ms,
            link_title=link_title)
        result = await _drive()
        after = await _probe_categories(
            executor, probe_cats, timeout_ms=timeout_ms,
            link_title=link_title)
    if probe_cats and not _probes_agree(before, after):
        # One automatic retry (D2) before failing closed.  The same
        # stage's clock is wound a SECOND time and accumulates: a retry
        # is work the run actually performed, not a free caveat.
        state.errors.append(f"{stage}: probe divergence — one retry")
        _write_status(state, status_cb)
        with _stage_clock(state, stage):
            before = await _probe_categories(
                executor, probe_cats, timeout_ms=timeout_ms,
                link_title=link_title)
            result = await _drive()
            after = await _probe_categories(
                executor, probe_cats, timeout_ms=timeout_ms,
                link_title=link_title)
        if not _probes_agree(before, after):
            raise PipelineError(
                "model_edited_during_decompile",
                "модель редактируется во время декомпайла",
                f"stage={stage}")
    state.stages_done.append(stage)
    _write_status(state, status_cb)
    return result, False


# ── merge helpers for paginated side extractions ─────────────────────────────
def _merge_curves(parts: list[CurveExtraction]) -> CurveExtraction:
    records: list[Any] = []
    failures: list[Any] = []
    for part in parts:
        records.extend(part.records)
        failures.extend(part.failures)
    return CurveExtraction(records=tuple(records), failures=tuple(failures))


def _merge_curtain(parts: list[CurtainExtraction]) -> CurtainExtraction:
    records: list[Any] = []
    failures: list[Any] = []
    for part in parts:
        records.extend(part.records)
        failures.extend(part.failures)
    return CurtainExtraction(records=tuple(records), failures=tuple(failures))


def _merge_profiles(parts: list[ProfileExtraction]) -> ProfileExtraction:
    # The stage is ALREADY paged (_SIDE_BATCH = 200), and "in one call"
    # from the old comment stopped being true back in the budgets wave.
    # Hence this function's law: EVERY ProfileExtraction tuple must be
    # listed here. A forgotten field doesn't crash and doesn't make
    # noise — it survives a single-batch test and silently disappears on
    # a real building, where there is more than one batch. This is
    # exactly how railing paths on K2 would vanish (543 sketch rows + 81
    # ceilings + 203 railings — that is clearly not one batch).
    records: list[Any] = []
    stairs: list[Any] = []
    failures: list[Any] = []
    railings: list[Any] = []
    for part in parts:
        records.extend(part.records)
        stairs.extend(part.stairs_run_paths)
        failures.extend(part.failures)
        railings.extend(part.railing_paths)
    return ProfileExtraction(
        records=tuple(records),
        stairs_run_paths=tuple(stairs),
        failures=tuple(failures),
        railing_paths=tuple(railings))


def _merge_family(
    parts: list[FamilyPlacementExtraction],
) -> FamilyPlacementExtraction:
    records: list[Any] = []
    failures: list[Any] = []
    for part in parts:
        records.extend(part.records)
        failures.extend(part.failures)
    return FamilyPlacementExtraction(tuple(records), tuple(failures))


def _merge_group(parts: list[GroupExtraction]) -> GroupExtraction:
    records: list[Any] = []
    failures: list[Any] = []
    for part in parts:
        records.extend(part.records)
        failures.extend(part.failures)
    return GroupExtraction(tuple(records), tuple(failures))


def _rows_of(payload: Any, key: str) -> list[Any]:
    """Extract a row list from a bridge payload for the parser-only stages.

    MINOR-10 (28.07 audit): an unrecognized response shape used to
    return ``[]`` — and that was worse than it looks. An empty index was
    written to disk as a valid artifact (``_is_valid_artifact`` only
    looks at file size), and the resume logic on the next run REUSED it
    instead of re-reading: one garbled payload permanently erased the
    stage from the decompile. §18.2 demands a receipt even for "an
    unrecognized response shape," and a receipt for the whole response
    is a typed stage refusal.
    """
    if isinstance(payload, Mapping):
        rows = payload.get(key)
        if rows is None:
            rows = payload.get("rows")
        if rows is None:
            rows = payload.get("elements")
        if isinstance(rows, list):
            return rows
    if isinstance(payload, list):
        return payload
    raise PipelineError(
        "side_payload_unrecognized",
        "ответ боковой стадии пришёл в неузнанной форме",
        f"key={key} type={type(payload).__name__}")


def _wire_failures_of(payload: Any) -> list[Any]:
    """The list of receipts from a bridge response; a missing key is an empty list.

    The ``failures`` key is mandatory under §18.2 for NEW emitters; here
    it is lenient just enough that the pipeline doesn't crash on a
    foreign/old response — a lost element will still be caught by the
    stage's count check, and caught by address.
    """
    if isinstance(payload, Mapping):
        failures = payload.get("failures")
        if failures is None:
            return []
        if isinstance(failures, list):
            return failures
        raise PipelineError(
            "side_payload_unrecognized",
            "квитанции боковой стадии пришли в неузнанной форме",
            f"type={type(failures).__name__}")
    return []


def _family_part(payload: Any) -> FamilyPlacementExtraction:
    """One family_placement batch: rows + receipts, both halves of the response."""
    return FamilyPlacementExtraction.from_rows(
        _rows_of(payload, "placements"),
        wire_failures=_wire_failures_of(payload))


def _group_part(payload: Any) -> GroupExtraction:
    """One group batch: rows + receipts."""
    return GroupExtraction.from_rows(
        _rows_of(payload, "groups"),
        wire_failures=_wire_failures_of(payload))


def _accounted_ids(part: Any) -> list[str]:
    """ids the batch SAID something about — via a row or a receipt."""
    ids: list[str] = []
    for record in getattr(part, "records", ()) or ():
        # ``record_element_id``, not ``record.element_id``: a curtain-wall
        # row's field is called ``wall_id``, and a direct read would
        # declare every SUCCESSFULLY read curtain wall lost.
        element_id = record_element_id(record)
        if element_id:
            ids.append(element_id)
    for failure in getattr(part, "failures", ()) or ():
        element_id = failure_element_id(failure)
        if element_id:
            ids.append(element_id)
    return ids


def _reconcile_side_stage(
    stage: str,
    *,
    requested: Sequence[str],
    accounted: Sequence[str],
) -> None:
    """A thin wrapper over the shared validator — so it's easy to swap out."""
    reconcile_side_stage(stage, requested=requested, accounted=accounted)


# ── persistence of a side extraction ────────────────────────────────────────
def _persist_json(path: Path, obj: Any) -> None:
    if obj is None:
        return
    if hasattr(obj, "to_json"):
        path.write_text(obj.to_json(), encoding="utf-8")
        return
    if hasattr(obj, "to_dict"):
        payload = obj.to_dict()
    elif isinstance(obj, Mapping):
        payload = dict(obj)
    else:  # pragma: no cover — every side product is dict-serializable
        return
    _atomic_write_json(path, payload)


def _is_valid_artifact(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


# ── side-artifact row counter (§18.2, MINOR-10) ─────────────────────────────
#
# "An artifact reused by the resume logic carries a row counter for
# verification on reuse." The counter lives in ONE run manifest, not
# inside each of the five indexes: putting it inside would mean changing
# the schema of all five (three of them are frozen formats with exact
# field verification) for the sake of a number that describes not the
# index but the RUN that recorded it. The manifest sits next to the
# indexes, is written atomically by the same run, and is read on resume.
#
# The absence of a stage's record is not a refusal but "wasn't
# measured": decompiles taken before this wave have no manifest, and
# declaring them unreusable would mean demanding a full archive re-read
# for the sake of form (the same deliberate migration as the workset
# fields in §18.4).
def _side_counts(extraction: Any) -> dict[str, int]:
    """THE RESUME VERIFICATION KEY. Must NOT be extended — see ``_side_breakdown``."""
    return {
        "rows": len(getattr(extraction, "records", ()) or ()),
        "failures": len(getattr(extraction, "failures", ()) or ()),
    }


def _side_breakdown(extraction: Any, stage: str) -> dict[str, int]:
    """What this stage's ``failures`` is made of: cuts versus responses.

    WHY A SEPARATE FUNCTION, NOT FIELDS IN ``_side_counts``: that
    dictionary is the RESUME VERIFICATION KEY (``_side_counts_agree``),
    and any new field in it would declare every already-taken decompile
    unreusable, demanding an archive re-read for the sake of form. The
    breakdown is written ALONGSIDE it and takes no part in the check.

    WHY HAVE THIS AT ALL. The ``SideFailureKind`` class and the full
    ``SIDE_FAILURE_KINDS`` dictionary were built on 29.07 exactly against
    this reading, and ``run.json`` carries them. The MANIFEST did not: it
    printed one word, ``failures``, and it lumped together three
    incomparable things. Measured 13.08 on ``len_ar_me_r24_v1`` (53 686
    rows), done from the manifest and therefore wrong:

        total "failures"              12 073   22.5% of rows — the manifest's headline
        ├─ no aspect                  10 267   a CORRECT negative answer
        │    curtain not_curtain       9 715 — the wall is NOT curtain, the reader is right
        ├─ wrong kind on input         1 710   the CALLER's filter, not the reader
        └─ a real cut                     96   0.18% — this is our actual work

    ``curtain`` tops the manifest with 99.5% "failure" and is a hundred
    percent healthy. Ranking stages by this column sends work exactly
    where there is none — and this has already happened twice: 29.07 on
    the tower (14 343 against 19 real) and 13.08 here. The instrument was
    fixed once, but the wrong one of its outputs was fixed.
    """
    cuts = 0
    determinations = 0
    untyped = 0
    for failure in tuple(getattr(extraction, "failures", ()) or ()):
        reason = resolved_typed_reason(failure, stage)
        if reason is None:
            untyped += 1
            continue
        kind = failure_kind(reason)
        if kind is SideFailureKind.CUT:
            cuts += 1
        elif kind is SideFailureKind.DETERMINATION:
            determinations += 1
    # ``untyped`` is printed ALWAYS, not only when it's nonzero: its
    # absence from the record is indistinguishable from zero, and it
    # must be zero, which is verified by a test. A silent field is not
    # proof.
    return {"cuts": cuts, "determinations": determinations,
            "failures_untyped": untyped}


def _requested_ids_digest(requested_ids: Sequence[str]) -> str:
    """Bind a dynamic side artifact to the exact compiler-produced request."""

    encoded = json.dumps(
        sorted(requested_ids),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_side_manifest(directory: Path) -> dict[str, Any]:
    manifest = _read_json(directory / _SIDE_MANIFEST_NAME) or {}
    stages = manifest.get("stages")
    return stages if isinstance(stages, dict) else {}


def _record_side_counts(
    directory: Path,
    stage: str,
    extraction: Any,
    link_title: str | None = None,
    requested_ids: Sequence[str] | None = None,
) -> None:
    stages = dict(_read_side_manifest(directory))
    # WHOSE document THIS stage read. The row counter catches a
    # substituted artifact but does NOT catch an artifact taken from a
    # different document: it has the same schema, and can easily have
    # exactly as many rows.
    #
    # The source is written FOR EACH STAGE, not once per directory:
    # stages are recomputed one at a time, and a shared record updated
    # by the first of them would declare the others' still-untouched
    # foreign indexes "ours."
    stage_manifest: dict[str, Any] = {
        **_side_counts(extraction),
        **_side_breakdown(extraction, stage),
        "source": link_title}
    if requested_ids is not None:
        stage_manifest.update({
            "requested_ids_count": len(requested_ids),
            "requested_ids_sha256": _requested_ids_digest(requested_ids),
        })
    stages[stage] = stage_manifest
    _atomic_write_json(directory / _SIDE_MANIFEST_NAME, {
        "schema_version": _SIDE_MANIFEST_VERSION,
        "stages": dict(sorted(stages.items())),
    })


def _side_counts_agree(
    directory: Path,
    stage: str,
    extraction: Any,
    link_title: str | None = None,
    requested_ids: Sequence[str] | None = None,
) -> bool:
    """Whether an already-existing stage index can be reused.

    Two different checks, and the second one appeared 30.07 together with
    link reading. The row counter catches a SUBSTITUTED artifact. It does
    not catch an artifact taken from a DIFFERENT DOCUMENT: a host's index
    has the exact same schema and can easily have exactly as many rows as
    a link's index. The ``snowdon_elec_v1`` directory is a live example
    of this: its indexes were taken on an order from a link but read from
    the host, and by the counter they are flawless.

    A directory taken BEFORE this wave recorded no source. While asking
    for the host, this changes nothing (the previous behavior). But if
    asking for the LINK, "whose is unknown" is not "probably ours": the
    stage is recomputed.
    """
    expected = _read_side_manifest(directory).get(stage)
    if not isinstance(expected, Mapping):
        # Static side requests are a pure function of frozen L0, so legacy
        # artifacts keep their old resume behaviour.  Dynamic requests (Tier
        # G atom ids) depend on the current compiler and must have an explicit
        # identity binding before they can be reused.
        return requested_ids is None
    if "source" in expected:
        if expected.get("source") != link_title:
            return False
    elif link_title is not None:
        return False
    if requested_ids is not None:
        if expected.get("requested_ids_count") != len(requested_ids):
            return False
        if expected.get("requested_ids_sha256") != _requested_ids_digest(
                requested_ids):
            return False
    return _side_counts(extraction) == {
        "rows": expected.get("rows"),
        "failures": expected.get("failures"),
    }


# ── passport markdown (thin operator-facing summary of the JSON passport) ────
def _passport_markdown(passport: Mapping[str, Any]) -> str:
    stats = passport.get("stats", {}) if isinstance(passport, Mapping) else {}
    verify = passport.get("verify_summary", {})
    lines = [
        f"# KIR Passport — {passport.get('doc_name', '?')}",
        "",
        f"- Revit: {passport.get('revit_version', '?')}",
        f"- change_stamp: `{passport.get('change_stamp', '?')}`",
        f"- gestalt: {passport.get('gestalt', 'unknown')}",
    ]
    if stats.get("is_partial_read"):
        # §18.4: a percentage computed on a partial read is printed ONLY
        # together with the marker — and before the percentages, not as
        # a footnote under them.
        lines.append(
            "- ⚠ ЧАСТИЧНОЕ ЧТЕНИЕ: рабочих наборов закрыто "
            f"{stats.get('worksets_closed', '?')} — цифры ниже описывают "
            "видимую часть модели, а не модель")
    # §18.1: the census comes BEFORE the percentages. The reader must
    # learn what the denominator is before seeing the numerator; the
    # order here is the law itself.
    summary = stats.get("census_summary_ru")
    if summary:
        lines.append(f"- перепись: {summary}")
    unscanned = stats.get("unscanned_by_category")
    if isinstance(unscanned, Mapping):
        # The whole of ``top``: the remainder below is computed from the
        # top-N boundary, and a slice of a slice would drop rows into
        # the gap between what's shown and "other."
        for row in unscanned.get("top", []):
            lines.append(
                f"  - {row.get('category')}: не читалось "
                f"{row.get('unscanned')} ({row.get('reason')})")
        if unscanned.get("other_categories"):
            lines.append(
                f"  - прочие {unscanned['other_categories']} категорий: "
                f"не читалось {unscanned.get('other_elements', '?')}")
    # §18.2: the receipts row stands RIGHT AFTER the census and BEFORE
    # the percentages. The census answers "what we didn't look at at
    # all," the receipts answer "what we looked at and didn't finish
    # looking at," and only after both answers does the percentage mean
    # what the reader thinks it means.
    receipts = stats.get("side_cuts_summary_ru")
    if receipts:
        lines.append(f"- квитанции срезов: {receipts}")
        by_stage = stats.get("side_failures_by_stage")
        if isinstance(by_stage, Mapping) and by_stage:
            # Per stage, a BREAKDOWN of "cut + answered" is printed, not
            # one sum. The sum read as a mass of refusals: on
            # 13A-RD-AR-K2_v33 the row "curtain 14343" was the largest
            # number in the passport, whereas there are 19 cuts there,
            # and 14 324 are "the wall is not curtain" answers, each of
            # which also has a full-fledged index row.
            cuts_by_stage = stats.get("side_cuts_by_stage") or {}
            answered_by_stage = (
                stats.get("side_determinations_by_stage") or {})
            detail = ", ".join(
                f"{stage} {cuts_by_stage.get(stage, 0)} срез"
                f" / {answered_by_stage.get(stage, 0)} отв"
                for stage in sorted(by_stage))
            lines.append(
                f"  - квитанций боковых индексов всего "
                f"{stats.get('side_failures_total', '?')} ({detail})")
    lines += [
        "",
        "## Stats",
        f"- elements: {stats.get('elements_total', '?')}",
        f"- ops lifted: {stats.get('ops_lifted', '?')}",
        f"- atoms: {stats.get('atoms', '?')}",
        f"- покрытие от ПРОЧИТАННОГО: "
        f"{stats.get('lifted_pct_extracted', '—')}%",
        f"- покрытие от ДОКУМЕНТА: "
        f"{stats.get('lifted_pct_document', '—')}"
        f"{'%' if stats.get('lifted_pct_document') is not None else ''}",
        f"- floors: {stats.get('floors', '?')}",
        f"- rooms: {stats.get('rooms', '?')}",
        f"- apartments: {stats.get('apartments', '?')}",
        "",
        "## Verify",
        f"- failed verdicts: {verify.get('failed_count', '?')}",
        f"- reversible: {verify.get('reversible', '?')}",
        "",
        "_Canonical machine-readable passport: `passport.json`._",
    ]
    return "\n".join(lines) + "\n"


def _persist_core_artifacts(
    directory: Path,
    passport: Mapping[str, Any],
    tree: Mapping[str, Any],
    name_result: Mapping[str, Any],
) -> Path:
    """Serialize the large frozen-tail artifacts outside the event loop.

    This helper deliberately preserves the former byte formats and write
    order.  It only gives the CPU-heavy JSON rendering and filesystem waits
    one explicit offload boundary; artifact ownership and contents do not
    move.
    """
    (directory / "passport.json").write_bytes(passport_bytes(passport))
    passport_md = directory / "passport.md"
    passport_md.write_text(_passport_markdown(passport), encoding="utf-8")

    # ``tree`` and NAME's tree are already JSON-shaped TypedDicts.
    _atomic_write_json(directory / "tree.json", tree)
    named_tree = name_result.get("tree")
    if isinstance(named_tree, Mapping):
        _atomic_write_json(directory / "named.json", named_tree)
    return passport_md


# ── the run ──────────────────────────────────────────────────────────────────
async def run_decompile(
    executor: BridgeExecutor,
    *,
    out_dir: str | os.PathLike[str],
    change_stamp: str,
    status_cb: Optional[StatusCallback] = None,
    cs_builders: Optional[Mapping[str, SideCsBuilder]] = None,
    timeout_ms: int = EXTRACT_TIMEOUT_MS,
    #: Capture not the host but its LINK with this Document.Title. The
    #: snapshot is separate, with its own stamp. The source is carried
    #: through to EVERY side stage and to the D2 probe around it: one
    #: snapshot — one document.
    link_title: str | None = None,
) -> DecompileRunResult:
    """Drive one live DECOMPILE run against ``executor``.

    Stages: metadata+categories (extract_document, resumable) → probe →
    per-stage side indexes (curve/sketch/curtain, each probe-guarded and
    batched, family_placement/group when a builder is registered) → cached
    detailed lift → fold(group_index) → name → verify → passport.  Every
    artifact is persisted under ``out_dir`` and every failure is a typed
    :class:`DecompileRunResult` with ``ok=False`` (I2 — never raises).
    """
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    state = _RunState(out_dir=directory, change_stamp=change_stamp)
    builders = dict(_default_cs_builders(link_title=link_title))
    if cs_builders:
        builders.update(cs_builders)

    if not isinstance(change_stamp, str) or not change_stamp:
        return _fail(state, status_cb, PipelineError(
            "bad_stamp", "change_stamp must be a non-empty string"))

    try:
        # ── stage 1: metadata + categories (resumable checkpoint) ──────────
        state.stage = "extract"
        _write_status(state, status_cb)
        l0_path = directory / "L0.jsonl"
        checkpoint = directory / "L0.checkpoint.json"
        revision_path = directory / _REVISION_PROOF_NAME
        revision_proof = _read_json(revision_path)
        expected_revision: str | None = None
        if revision_proof is not None:
            if (revision_proof.get("schema_version") !=
                    _REVISION_PROOF_VERSION
                    or revision_proof.get("change_stamp") != change_stamp
                    or not isinstance(
                        revision_proof.get("fingerprint"), str)
                    or not revision_proof.get("fingerprint")):
                raise PipelineError(
                    "revision_proof_invalid",
                    "persisted document revision proof is invalid")
            expected_revision = revision_proof["fingerprint"]
        elif checkpoint.exists():
            # A checkpoint with no committed header contains no document data
            # and may establish its first proof now.  Once any L0 bytes were
            # committed, however, their revision is unknowable and resume must
            # fail closed rather than mix a legacy snapshot with live reads.
            prior_checkpoint = _read_json(checkpoint)
            empty_checkpoint = bool(
                prior_checkpoint
                and prior_checkpoint.get("header_written") is False
                and prior_checkpoint.get("committed_offset") == 0)
            if not empty_checkpoint:
                raise PipelineError(
                    "revision_proof_missing",
                    "persisted L0 checkpoint has no document revision proof")

        def _persist_revision(fingerprint: str) -> None:
            _atomic_write_json(revision_path, {
                "schema_version": _REVISION_PROOF_VERSION,
                "change_stamp": change_stamp,
                "fingerprint": fingerprint,
            })

        guarded_executor = _RevisionGuardedExecutor(
            executor, expected=expected_revision,
            on_first=_persist_revision if expected_revision is None else None)

        # Bind the source requirements to the exact already-open document
        # before any L0 bytes are consumed.  This is a separate side artifact:
        # frozen L0 1.0 remains byte-compatible, while same-document rebuild
        # can later prove that every pinned level/type/symbol still denotes the
        # same Revit object (ElementId + UniqueId + VersionGuid).
        state.stage = "open_model_profile"
        _write_status(state, status_cb)
        open_model = await capture_open_model_profile(
            guarded_executor, timeout_ms=timeout_ms)
        revision_fingerprint = guarded_executor.revision
        if not isinstance(revision_fingerprint, str) \
                or not revision_fingerprint:
            raise PipelineError(
                "open_model_profile_unbound",
                "open model profile has no document revision proof")
        open_model = replace(
            open_model,
            revision_proof=RevisionProof(
                change_stamp, revision_fingerprint),
        )
        _atomic_write_json(
            directory / _OPEN_MODEL_PROFILE_NAME, open_model.to_dict())
        state.stages_done.append("open_model_profile")
        _write_status(state, status_cb)

        # ONE window-wait budget for the whole run: extraction and the
        # side stages spend it together. Otherwise a dead window would
        # cost the full ceiling per stage, and "five minutes once" would
        # turn into half an hour.
        from kir.decompile.extract import _WindowWaitBudget
        window_budget = _WindowWaitBudget()

        # THE LONGEST STAGE MUST NAME ITSELF. Measured 30.07 on a live
        # tower: reading ran for 41 minutes, L0 grew to 88 MB, and
        # status.json asserted `stage=open_model_profile, done 0/0` the
        # entire time — the stage was set BEFORE reading and never
        # touched again. Telling "running normally" from "hung" apart
        # was only possible by file size, that is, by no instrument at
        # all.
        state.stage = "extract"
        state.done = 0
        state.total = 0
        _write_status(state, status_cb)

        def _extract_progress(progress: Any) -> None:
            # done/total here are counted in CATEGORIES, in the side
            # stages they're counted in batches. Both are honest as long
            # as the stage is named alongside: `stage` sets the
            # counter's meaning, and confusing them is the same mistake
            # as confusing coverage denominators.
            state.done = progress.categories_done
            state.total = progress.categories_total
            state.elements_total = progress.elements
            _write_status(state, status_cb)

        with _stage_clock(state, "extract"):
            extraction = await extract_document(
                guarded_executor,
                change_stamp=change_stamp,
                output_path=str(l0_path),
                checkpoint_path=str(checkpoint),
                resume=True,
                timeout_ms=timeout_ms,
                window_budget=window_budget,
                on_progress=_extract_progress,
                link_title=link_title,
            )
        # THE EXTRACTION BREAKDOWN CARRIES THROUGH TO run.json. Keeping
        # it only in the checkpoint would mean: to find out where an
        # hour went, you'd have to know the resume service file exists.
        # The total lives next to the percentages; the per-category rows
        # stay in the checkpoint.
        from kir.decompile.extract import _timing_totals
        state.timing_extract = {
            **_timing_totals(extraction.timing),
            "by_category": dict(extraction.timing),
        }
        state.elements_total = extraction.element_count
        if extraction.partial_categories:
            # ``stream_complete`` means the JSONL transaction has a committed
            # footer; it does NOT turn partial category evidence into an
            # authoritative model snapshot.  LIFT/A5 must never consume it.
            state.stages_done.append("extract")
            return _fail(state, status_cb, PipelineError(
                "snapshot_non_authoritative",
                "L0 extraction contains partial categories; lift is blocked",
                ", ".join(extraction.partial_categories)))
        document = await _timed(state, "materialize_l0",
            _offload(L0JSONLReader(l0_path).materialize))
        # §18.4: the marker is raised RIGHT AFTER materialization —
        # before the side indexes, the lift, and any percentage.
        # Measured 27.07: 17 closed worksets out of 18 gave 11 elements
        # instead of 2016, with every status showing complete.
        state.is_partial_read = document.is_partial_read
        state.partial_read_measured = True
        state.worksets_closed = document.worksets_closed
        # §18.1: the document's accounting is reconciled RIGHT AFTER
        # materialization — before the side indexes, the lift, and any
        # percentage. An identity mismatch (more was extracted than
        # exists in the document) is a typed run error, not a log line:
        # the claim "N were read" is refuted by the census, and
        # everything built afterward would stand on it.
        balance = await _timed(state, "census",
            _offload(reconcile_census, document))
        state.census = balance.to_dict()
        if not balance.balanced:
            state.stages_done.append("extract")
            return _fail(state, status_cb, PipelineError(
                "census_balance_mismatch",
                "бухгалтерия документа не сходится с переписью",
                "; ".join(
                    str(error.get("detail") or error.get("code"))
                    for error in balance.errors)[:400]))
        state.stages_done.append("extract")
        _write_status(state, status_cb)

        # THE REVIT VERSION BECOMES KNOWN ONLY HERE. C# builders are
        # assembled before reading (the document doesn't exist yet), but
        # the tag stage needs the version: its surface splits at 2022,
        # and one body for six targets would fail to build on either
        # 2021 or 2023+.
        #
        # TWO CONDITIONS, AND BOTH ARE CHECKED AGAINST THE ASSEMBLED SET,
        # NOT THE FACTORY. ``"tag" in builders`` — only someone who
        # already registered the stage gets to rebind it: a substituted
        # factory is entitled to NOT give the stage, and then the honest
        # answer is a skip, not a resurrection. The second condition — a
        # foreign builder always outranks the default.
        #
        # The factory is deliberately NOT called a second time here: it
        # has already handed out EIGHT stages, and a second call for the
        # sake of ONE would re-manufacture seven foreign ones. The
        # builder is assembled with the same expression as in the
        # factory — straight from ``build_tag_extract_cs`` — and the
        # SOURCE the rebuilt tag carries with it: a stage that lost it on
        # rebinding would read the host exactly where the other seven
        # read the link.
        if "tag" in builders and not (cs_builders and "tag" in cs_builders):
            builders["tag"] = (
                lambda ids, __version=document.revit_version,
                __link=link_title:
                    build_tag_extract_cs(
                        list(ids), revit_version=__version,
                        link_title=__link))

        # ── stage 2: side indexes (each probe-guarded + batched + resumable) ─
        curve = await _side_or_resume(
            guarded_executor, document, "curve", extract_curves, _merge_curves,
            builders, state, status_cb, directory / "curve.index.json",
            CurveExtraction, timeout_ms=timeout_ms, window_budget=window_budget,
            link_title=link_title)
        profiles = await _side_or_resume(
            guarded_executor, document, "sketch", extract_sketch_profiles,
            _merge_profiles, builders, state, status_cb,
            directory / "sketch.index.json", ProfileExtraction,
            timeout_ms=timeout_ms, window_budget=window_budget,
            link_title=link_title)
        curtain = await _side_or_resume(
            guarded_executor, document, "curtain", extract_curtain_topology,
            _merge_curtain, builders, state, status_cb,
            directory / "curtain.index.json", CurtainExtraction,
            timeout_ms=timeout_ms, window_budget=window_budget,
            link_title=link_title)
        family = await _side_or_resume(
            guarded_executor, document, "family_placement",
            _family_part, _merge_family,
            builders, state, status_cb,
            directory / "family_placement.index.json",
            FamilyPlacementExtraction, timeout_ms=timeout_ms,
            window_budget=window_budget, link_title=link_title)
        groups = await _side_or_resume(
            guarded_executor, document, "group",
            _group_part, _merge_group,
            builders, state, status_cb, directory / "group.index.json",
            GroupExtraction, timeout_ms=timeout_ms, whole_model=True,
            window_budget=window_budget, link_title=link_title)
        annotations = await _side_or_resume(
            guarded_executor, document, "annotation",
            extract_annotations, merge_annotations,
            builders, state, status_cb,
            directory / "annotation.index.json",
            AnnotationExtraction, timeout_ms=timeout_ms,
            window_budget=window_budget, link_title=link_title)
        tags = await _side_or_resume(
            guarded_executor, document, "tag",
            extract_tags, merge_tags,
            builders, state, status_cb,
            directory / "tag.index.json",
            TagExtraction, timeout_ms=timeout_ms,
            window_budget=window_budget, link_title=link_title)
        dimensions = await _side_or_resume(
            guarded_executor, document, "dimension",
            extract_dimensions, merge_dimensions,
            builders, state, status_cb,
            directory / "dimension.index.json",
            DimensionExtraction, timeout_ms=timeout_ms,
            window_budget=window_budget, link_title=link_title)
        mep_systems = await _side_or_resume(
            guarded_executor, document, "mep_system",
            extract_mep_systems, merge_mep_systems,
            builders, state, status_cb,
            directory / "mep_system.index.json",
            MepSystemExtraction, timeout_ms=timeout_ms,
            window_budget=window_budget, link_title=link_title)
        joins = await _side_or_resume(
            guarded_executor, document, "join",
            extract_joins, merge_joins,
            builders, state, status_cb,
            directory / "join.index.json",
            JoinExtraction, timeout_ms=timeout_ms,
            window_budget=window_budget, link_title=link_title)

        if _read_cancel(directory):
            return _cancelled(state, status_cb)

        # §18.2: the receipt aggregate is assembled RIGHT AFTER the side
        # stages — before the lift and before any percentage, so that
        # "how much we didn't finish looking at" is known before "how
        # much we lifted."
        side_products: dict[str, Any] = {
            "curve": curve,
            "sketch": profiles,
            "curtain": curtain,
            "family_placement": family,
            "group": groups,
            "annotation": annotations,
            "tag": tags,
            "dimension": dimensions,
            "mep_system": mep_systems,
            "join": joins,
        }
        side_failures = summarize_side_failures(side_products)
        state.side_failures = side_failures
        _write_status(state, status_cb)

        # ── stage 3: frozen offline tail with the injected lift cache ──────
        state.stage = "lift"
        _write_status(state, status_cb)
        profile_index = profiles.to_dict() if profiles is not None else None
        family_index = (
            parse_family_placement_index(family)
            if family is not None else {})
        group_idx = parse_group_index(groups) if groups is not None else None

        lift_result = await _timed(state, "lift", _offload(
            cached_lift_document_detailed,
            document,
            profile_index=profile_index,
            family_placement_index=family_index,
            # The curve index is assembled above (a bridge round-trip +
            # curve.index.json) and used to be LOST here: arc walls were
            # lifted as chords, whereas the A5-relift passes the same
            # index — the original saw less context than the rebuilt
            # side, and the comparison ran against a degraded
            # representation (arch review 2026-07-25 §3.3).
            wall_curve_index=curve,
            # The curtain-wall index — the same thing, one wave later:
            # without it a curtain-wall cell is inexpressible, and panels
            # stay atoms (design 2026-07-28).
            curtain_index=curtain,
            # Annotation: without this index every note stays an honest
            # source_contract_gap atom — exactly as before the wave.
            annotation_index=annotations,
            # Without this index every tag stays an honest
            # source_contract_gap atom — exactly as before the wave.
            tag_index=tags,
            # Without this index every dimension stays an honest
            # source_contract_gap atom — exactly as before the wave
            # (measured on k2_ar_rd_v8: 13 905 dimensions = 13 905 such
            # atoms, EVERY LAST ONE).
            dimension_index=dimensions,
            mep_system_index=mep_systems,
            # 🔴 BOTH INDEXES ARE ASSEMBLED ABOVE AND WEREN'T REACHING
            # THE LIFT (E-30). Without them the result's `joins` and
            # `groups` stay `None` (`lift.py`: «`join_index is None`
            # means "the index was NOT SUPPLIED"»), meaning every live
            # decompile said "wasn't asked for" in a case where the
            # stage had ALREADY read the links and written
            # `join.index.json`. The orchestrator has been passing both
            # since 22.08 (`orchestrator.py` carries a red comment about
            # this very seam); the fix never reached here.
            #
            # 🔴 THIS IS NOT YET DELIVERY TO THE PROGRAM, AND MUST NOT BE
            # CONFUSED WITH IT. The lifted relations go no further:
            # `tree.json` carries only leaves. The fix buys a NUMBER
            # instead of silence — see `relations_reach` and
            # `side_contract.RELATIONS_UNDELIVERED_REASON`.
            #
            # The risk of feeding this is MEASURED, not estimated
            # (29.08.2026, live corpus, read-only): `lift_joins` on all 7
            # decompiles with `join.index.json` and `lift_groups` on 4
            # decompiles with `group.index.json` — NOT A SINGLE refusal,
            # 0 out of 11.
            join_index=joins,
            group_index=group_idx,
            enabled=True,
            cache_dir=str(directory / "lift_cache"),
        ))
        l1_nodes = lift_result.nodes
        # F-260/F-250: ask the cache WHAT it failed to read. Asked AFTER
        # the stage — earlier there would be nothing to answer with, and
        # an empty answer would mean "wasn't asked," not "no refusals."
        state.lift_cache_refusals = list(
            lift_cache_refusals(directory / "lift_cache"))

        # ── stage 4: Tier G only for atoms that semantics could not lift ──
        # This is deliberately after LIFT.  Extracting full geometry for all
        # L0 elements would waste the Revit budget and create a competing
        # representation for already-typed semantic ops.  Generator children
        # are excluded because their parent recreates them by construction.
        atom_ids = _geometry_atom_ids(l1_nodes)
        elements_by_id = {
            element.element_id: element for element in document.elements
        }
        missing_atom_ids = sorted(set(atom_ids) - set(elements_by_id))
        if missing_atom_ids:
            raise SideStageContractError(
                "geometry: atom ids are absent from L0: "
                + ", ".join(missing_atom_ids[:8]))
        categories_by_id = {
            element_id: elements_by_id[element_id].category
            for element_id in atom_ids
        }
        geometry_path = directory / "geometry.bundle.json"
        geometry = await _side_or_resume(
            guarded_executor,
            document,
            "geometry",
            extract_geometry,
            merge_geometry_extractions,
            builders,
            state,
            status_cb,
            geometry_path,
            GeometryExtraction,
            timeout_ms=timeout_ms,
            window_budget=window_budget,
            link_title=link_title,
            requested_ids=atom_ids,
            probe_categories=sorted(set(categories_by_id.values())),
            loader=lambda persisted: GeometryExtraction.from_json(
                persisted, categories_by_id=categories_by_id),
        )
        side_products["geometry"] = geometry
        if geometry is not None:
            current_revision = guarded_executor.revision
            if not isinstance(current_revision, str) or not current_revision:
                raise SideStageContractError(
                    "geometry: source revision proof is unavailable")
            geometry_proof = GeometryArtifactProof.bind(
                change_stamp=change_stamp,
                revision_fingerprint=current_revision,
                geometry_bundle=geometry_path.read_bytes(),
                leaves=l1_nodes,
            )
            _atomic_write_json(
                directory / _GEOMETRY_PROOF_NAME,
                geometry_proof.to_dict(),
            )
        side_failures = summarize_side_failures(side_products)
        state.side_failures = side_failures
        _write_status(state, status_cb)

        if _read_cancel(directory):
            return _cancelled(state, status_cb)

        state.stage = "fold"
        _write_status(state, status_cb)
        tree = await _timed(state, "fold", _offload(
            fold_document, document, l1_nodes, group_index=group_idx))

        state.stage = "name"
        _write_status(state, status_cb)
        name_result = await _timed(state, "name",
            _offload(name_document, document, tree))

        state.stage = "verify"
        _write_status(state, status_cb)
        # The family axis is the only thing measured to separate name
        # collisions inside one document (115 of 275 cells, 2026-08-11),
        # and it lives in a side index the manifest was never handed.
        manifest = await _timed(state, "verify", _offload(
            build_dependency_manifest,
            document,
            family_placement=(family_index if family is not None else None),
        ))
        build_status = BuildStatuses.initial(
            unresolved_dependencies=manifest.unresolved_count)
        equivalence = EquivalenceClaim.unverified(
            EquivalenceScope.NATIVE_SEMANTIC)
        verify_result = await _timed(state, "verify", _offload(
            verify_document,
            document, tree, l1_nodes, dependency_manifest=manifest))
        _atomic_write_json(directory / "verify.json", verify_result.to_dict())

        state.stage = "passport"
        _write_status(state, status_cb)
        passport = await _timed(state, "passport", _offload(
            build_passport,
            document, tree, name_result, verify_result,
            geometry=geometry,
            dependencies=manifest, build_status=build_status,
            equivalence=equivalence, group_index=group_idx))
        # §18.4: the passport's percentages are computed over what was
        # SEEN. The partial-read marker is placed in the same section as
        # the percentages — so that it can't be read separately from
        # them.
        passport = passport.to_dict()
        ops_lifted = int(passport["stats"].get("ops_lifted") or 0)
        passport["stats"] = {
            **passport["stats"],
            "is_partial_read": document.is_partial_read,
            "worksets_closed": document.worksets_closed,
            # §18.1: the denominator. ``lifted_pct_extracted`` is the
            # historical base (out of what was read),
            # ``lifted_pct_document`` is the document base. Both are
            # printed together on purpose: one answers "how good is the
            # compiler on what it sees," the other "what fraction of the
            # building is expressed at all," and substituting the second
            # for the first means calling a property of the category
            # table a property of the compiler.
            **balance.to_dict(),
            "census_summary_ru": balance.summary_ru(),
            # §18.2: the receipts stand in the SAME section as the
            # percentages for the same reason as the partial-read
            # marker — reading a percentage without seeing the cuts must
            # not be possible.
            **side_failures,
            "side_cuts_summary_ru": receipts_summary_ru(side_failures),
            # §18.2b: "how many relations were lifted and how many of
            # them made it through." It stands IN THE SAME section as
            # the percentages for the same reason as the cuts: reading
            # "so-and-so many operations" without seeing that the
            # building's 1 758 joins contributed NOT ONE to that number
            # must not be possible.
            **relations_reach(lift_result.joins, lift_result.groups),
            "lifted_pct_extracted": balance.extracted_pct(ops_lifted),
            "lifted_pct_document": balance.document_pct(ops_lifted),
        }
        passport_md = await _offload(
            _persist_core_artifacts,
            directory,
            passport,
            tree,
            name_result,
        )

        # ── merkle: the building content's address next to the building
        # itself ────────────────────────────────────────────────────────
        # The flag is OFF by default, and off means literally the same
        # tree and the same passport, byte for byte: not one extra file,
        # not one extra line in `timing`.  Computed over the ALREADY
        # folded `tree` — that is exactly the input `merkle` expects, so
        # there is no adapter. A failure of the layer does NOT crash the
        # run: the passport is the stage's product, `merkle.json` is an
        # attachment to it; but it doesn't stay silent either — a
        # failure lands in that same file with `ok:false`, because "no
        # repeats found" and "computation failed" must look different.
        if merkle_enabled():
            merkle_json = await _timed(state, "merkle", _offload(
                building_report, tree, label=directory.name))
            _atomic_write_json(directory / _MERKLE_NAME, merkle_json)
            if not merkle_json.get("ok"):
                error = merkle_json.get("error") or {}
                state.errors.append(
                    f"merkle: {error.get('type')}: {error.get('message')}")

        # ── journal: a decompile as a REVISION of the building, not as
        # a standalone fact ────────────────────────────────────────────
        # Before this wave, two readings of the same building were
        # connected by nothing: there are 52 decompiles on disk, they
        # add up to 10 buildings by `doc_name` (the facade has 18
        # revisions), and "what changed since last time" cost holding
        # both `tree.json`s and computing the diff from scratch. The
        # `journal` layer had known how to keep such a log since 27.07,
        # but nobody called it; here it gets a caller.
        #
        # The journal is SHARED for the building and sits next to the
        # run directories (`_journals/`), not inside this run: inside,
        # it couldn't answer the one question it exists for — which
        # revision came before.
        #
        # The flag is OFF by default, and off means the previous bytes:
        # no `journal.json`, no line in `timing`. A failure of the layer
        # does NOT crash the run — the passport is the stage's product,
        # the journal is an attachment to it — but it doesn't stay
        # silent either: a failure lands in that same file with
        # `ok:false`, because "there's no history yet" and "failed to
        # append" must look different.
        if journal_enabled():
            journal_json = await _timed(state, "journal", _offload(
                record_revision,
                directory.parent,
                doc_name=getattr(document, "doc_name", ""),
                doc_stamp=change_stamp,
                out_dir=str(directory),
                tree=tree,
                revit_version=str(
                    getattr(document, "revit_version", "") or ""),
            ))
            _atomic_write_json(directory / _JOURNAL_NAME, journal_json)
            if not journal_json.get("ok"):
                error = journal_json.get("error") or {}
                state.errors.append(
                    f"journal: {error.get('type')}: {error.get('message')}")

        # ── building_graph: the BUILDING'S STATE next to the decompile
        # ───────────────────────────────────────────────────────────────
        # 🔴 WHAT IS BEING CLOSED HERE. `building_graph.py` knew ten
        # assembly relations, three modalities, and the census as a
        # building precondition — and was never called from prod, NOT
        # ONCE: the only call to `graph_from_l0` outside the tests lived
        # in `tools/address_spine.py:172`, and `graph_store` admitted as
        # much in its own header ("not wired into the live pipeline").
        #
        # THE INPUTS ARE TAKEN FROM WHAT THE RUN HAS ALREADY COMPUTED,
        # not recomputed: `join.index.json` is written above, `link`
        # records sit in the same L0, the host's class is in
        # `family_placement.index.json`, spawned children are in L1
        # atoms. Every unsupplied input EXTINGUISHES AN EDGE KIND, and
        # the graph calls this `census.sources_absent` rather than
        # staying silent as zero.
        #
        # THE FLAG IS ON BY DEFAULT AS OF 22.08.2026 (the census agreed
        # on 76 out of 76 corpus decompiles, 0 refusals — see the
        # breakdown in `building_graph.building_graph_enabled`). Turned
        # off by the explicit word `KUKAI_IR_BUILDING_GRAPH=0`, and off
        # means the previous bytes: no `building_graph.json`, no line in
        # `timing`.
        #
        # A STAGE FAILURE DOES NOT CRASH THE RUN — the passport is the
        # stage's product, the graph is an attachment to it — but it
        # does NOT STAY SILENT either: it lands in `state.errors`,
        # because "the graph wasn't asked for" and "the graph didn't
        # come together" must look different. An unsupplied source is
        # NOT put into `errors`: that is not a run failure, and it
        # already has its own carrier — `census.sources_absent` inside
        # the artifact itself. A second carrier of one fact drifts
        # apart, and this house has already paid for that.
        if building_graph_enabled():
            try:
                await _timed(state, "building_graph", _offload(
                    _build_and_write_graph, directory, l1_nodes,
                    family_index if family is not None else {},
                    joins))
                state.stages_done.append("building_graph")
            except Exception as exc:  # noqa: BLE001 — the refusal is named, not swallowed silently
                state.errors.append(
                    f"building_graph: {type(exc).__name__}: {exc}")

        state.stage = "done"
        state.stages_done.append("passport")
        _write_status(state, status_cb)

        result = DecompileRunResult(
            ok=True,
            out_dir=str(directory),
            change_stamp=change_stamp,
            stages=tuple(state.stages_done),
            passport_path=str(passport_md),
            slo_violations=state.slo_violations,
            timing=state.timing_dict(),
            elements_total=state.elements_total,
            # 🔴 THE SECOND HALF OF THE 20.08 FIX — WITHOUT THIS LINE IT
            # WAS A VACUUM. The `partial_read_measured` guard was set up
            # in TWO dataclasses (`_RunState` and `DecompileRunResult`),
            # but the VALUE was assigned to only one: `pipeline.py:1708`
            # raises it onto `state`, and `status.json` prints the
            # marker correctly. `run.json` is built FROM HERE, the field
            # never traveled here, the default `False` remained — and
            # the `is_partial_read` key disappeared from run.json for
            # EVERY run, complete and partial alike.
            # Measured 22.08.2026 over the `backend/data/decompile`
            # corpus: the key is carried by 48 run.json files out of 83
            # — ALL of them taken BEFORE commit `e8d21051` (20.08); not
            # one run after it has the key, whereas status.json carries
            # it for 52. This is a named form, and it's recorded in this
            # same house: "a patch made of two halves needs two
            # controls," and the test that turned red was exactly the
            # one demanding a FALSE FLAG instead of ABSENCE.
            partial_read_measured=state.partial_read_measured,
            is_partial_read=state.is_partial_read,
            worksets_closed=state.worksets_closed,
            census=balance.to_dict(),
            ops_lifted=ops_lifted,
            atoms=int(passport["stats"].get("atoms") or 0),
            side_failures=side_failures,
            lift_cache_refusals=list(state.lift_cache_refusals),
        )
        _atomic_write_json(directory / _RUN_NAME, result.to_dict())
        return result

    except PipelineError as exc:
        if exc.code == "cancelled":
            return _cancelled(state, status_cb)
        return _fail(state, status_cb, exc)
    except DocumentRevisionError as exc:
        return _fail(state, status_cb, PipelineError(
            "model_edited_during_decompile",
            "document revision changed during decompile", str(exc)))
    except TemplateCompileError as exc:
        # OUR defect, not a silent window and not a Revit refusal. A
        # separate code is needed because a report reader decides WHERE
        # to look based on it: "extract_failed" used to point at Revit,
        # where everything was fine.
        return _fail(state, status_cb, PipelineError(
            "template_compile_failed",
            "серверный шаблон не скомпилировался — до Revit не доехало "
            "ничего; чинить наш эмиттер, а не окно",
            str(exc)))
    except OpenModelProfileError as exc:
        return _fail(state, status_cb, PipelineError(
            "open_model_profile_invalid",
            "профиль открытой модели нарушает контракт", str(exc)))
    except SideStageContractError as exc:
        # §18.2: the stage lost ids it had ordered and left no receipt
        # for them. This is a RUN FAILURE, not a warning: everything
        # built afterward would rest on the claim "so many elements
        # aren't expressible," when in fact they were never read.
        return _fail(state, status_cb, PipelineError(
            "side_stage_count_mismatch",
            "боковая стадия потеряла элементы без квитанции", str(exc)))
    except ExtractionError as exc:
        return _fail(state, status_cb, PipelineError(
            "extract_failed", "извлечение L0 прервано", str(exc)))
    except Exception as exc:  # noqa: BLE001 — absolute fail-closed, typed only
        return _fail(state, status_cb, PipelineError(
            "internal", "внутренняя ошибка декомпайла", repr(exc)))


async def _side_or_resume(
    executor: BridgeExecutor,
    document: L0Document,
    stage: str,
    parse: Callable[[Any], Any],
    merge: Callable[[list[Any]], Any],
    builders: Mapping[str, SideCsBuilder],
    state: _RunState,
    status_cb: Optional[StatusCallback],
    persist_path: Path,
    from_dict_type: Any,
    *,
    timeout_ms: int,
    whole_model: bool = False,
    window_budget: Any = None,
    link_title: str | None = None,
    requested_ids: Sequence[str] | None = None,
    probe_categories: Sequence[str] | None = None,
    loader: Callable[[str], Any] | None = None,
) -> Optional[Any]:
    """Reuse a valid persisted side index; otherwise run and persist the stage."""
    directory = persist_path.parent
    if _is_valid_artifact(persist_path):
        try:
            persisted = persist_path.read_text(encoding="utf-8")
            loaded = (
                loader(persisted)
                if loader is not None
                else from_dict_type.from_json(persisted))
        except Exception:  # noqa: BLE001 — corrupt artifact ⇒ recompute
            loaded = None
        # §18.2/MINOR-10: an artifact is reused only if its contents
        # match the counter recorded by the run that made it. Otherwise
        # disk could hold (and used to hold) an empty but syntactically
        # valid stage — and it would silently stand in for reading.
        if loaded is not None and _side_counts_agree(
                directory, stage, loaded, link_title, requested_ids):
            if stage not in state.stages_done:
                state.stages_done.append(stage)
            return loaded
        if loaded is not None:
            state.errors.append(f"{stage}: side_index_count_mismatch — пересчёт")
    extraction, skipped = await _run_side_stage(
        executor, document, stage, parse, merge, builders, state, status_cb,
        timeout_ms=timeout_ms, whole_model=whole_model,
        window_budget=window_budget, link_title=link_title,
        requested_ids=requested_ids, probe_categories=probe_categories)
    if skipped or extraction is None:
        return None
    _persist_json(persist_path, extraction)
    _record_side_counts(
        directory, stage, extraction, link_title, requested_ids)
    return extraction


def _fail(
    state: _RunState,
    status_cb: Optional[StatusCallback],
    exc: PipelineError,
) -> DecompileRunResult:
    state.stage = "error"
    state.errors.append(f"{exc.code}: {exc.message}")
    _write_status(state, status_cb)
    result = DecompileRunResult(
        ok=False,
        out_dir=str(state.out_dir),
        change_stamp=state.change_stamp,
        stages=tuple(state.stages_done),
        error=exc.to_dict(),
        slo_violations=state.slo_violations,
        timing=state.timing_dict(),
        elements_total=state.elements_total,
        # The same wire as for a success. For a FAILURE it matters more:
        # the 20.08 run crashed BEFORE materialization, which is the
        # only place the marker gets assigned — and without
        # `partial_read_measured` run.json would have printed `false`,
        # that is, "read completely," for a run that failed EXACTLY
        # because of incomplete reading. Here the guard stays `False`,
        # and the key is honestly absent.
        partial_read_measured=state.partial_read_measured,
        is_partial_read=state.is_partial_read,
        worksets_closed=state.worksets_closed,
        # §18.1: a failed run must carry away the same numbers. A run
        # that failed BECAUSE OF identity can't be explained without
        # them, and a run that failed later can't be assessed.
        census=dict(state.census),
        # The same wire as for a success: a run that failed AFTER the
        # lift stage must carry away the cache's refusal reason,
        # otherwise "a hit in five minutes" will stay a guess (F-260/
        # F-250).
        lift_cache_refusals=list(state.lift_cache_refusals),
    )
    _atomic_write_json(state.out_dir / _RUN_NAME, result.to_dict())
    return result


def _cancelled(
    state: _RunState,
    status_cb: Optional[StatusCallback],
) -> DecompileRunResult:
    state.stage = "cancelled"
    _write_status(state, status_cb)
    result = DecompileRunResult(
        ok=False,
        out_dir=str(state.out_dir),
        change_stamp=state.change_stamp,
        stages=tuple(state.stages_done),
        error={"code": "cancelled", "message": "прогон отменён; можно продолжить"},
        cancelled=True,
        slo_violations=state.slo_violations,
        timing=state.timing_dict(),
        elements_total=state.elements_total,
        # The same wire as for a success and for a failure; see the
        # argument there.
        partial_read_measured=state.partial_read_measured,
        is_partial_read=state.is_partial_read,
        worksets_closed=state.worksets_closed,
        # §18.1: a failed run must carry away the same numbers. A run
        # that failed BECAUSE OF identity can't be explained without
        # them, and a run that failed later can't be assessed.
        census=dict(state.census),
        # The same wire as for a success: a run that failed AFTER the
        # lift stage must carry away the cache's refusal reason,
        # otherwise "a hit in five minutes" will stay a guess (F-260/
        # F-250).
        lift_cache_refusals=list(state.lift_cache_refusals),
    )
    _atomic_write_json(state.out_dir / _RUN_NAME, result.to_dict())
    return result


__all__ = [
    "DecompileRunResult",
    "PipelineError",
    "read_status",
    "request_cancel",
    "run_decompile",
]
