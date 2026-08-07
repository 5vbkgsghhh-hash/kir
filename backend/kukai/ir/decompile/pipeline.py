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
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from kukai.ir.contracts import RevisionProof
from kukai.ir.open_model import (
    OpenModelProfileError,
    capture_open_model_profile,
)
from kukai.ir.decompile.curtain_extract import (
    CurtainExtraction,
    build_curtain_extract_cs,
    extract_curtain_topology,
)
from kukai.ir.decompile.curve_extract import (
    CurveExtraction,
    build_curve_extract_cs,
    extract_curves,
)
from kukai.ir.decompile.annotation_extract import (
    ANNOTATION_CATEGORIES,
    AnnotationExtraction,
    build_annotation_extract_cs,
    extract_annotations,
    merge_annotations,
)
from kukai.ir.decompile.tag_extract import (
    TAG_CATEGORIES,
    TagExtraction,
    build_tag_extract_cs,
    extract_tags,
    merge_tags,
)
from kukai.ir.decompile.mep_system_extract import (
    MEP_SYSTEM_CATEGORIES,
    MepSystemExtraction,
    build_mep_system_extract_cs,
    extract_mep_systems,
    merge_mep_systems,
)
from kukai.ir.decompile.census import CensusBalance, reconcile_census
from kukai.ir.decompile.dependencies import build_dependency_manifest
from kukai.ir.decompile.extract import (
    BridgeExecutor,
    DocumentRevisionError,
    ExtractionError,
    TemplateCompileError,
    build_category_probe_cs,
    extract_document,
    L0JSONLReader,
)
from kukai.ir.decompile.family_placement_extract import (
    FamilyPlacementExtraction,
    build_family_placement_extract_cs,
    parse_family_placement_index,
)
from kukai.ir.decompile.side_contract import (
    SideStageContractError,
    failure_element_id,
    receipts_summary_ru,
    reconcile_side_stage,
    record_element_id,
    summarize_side_failures,
)
from kukai.ir.decompile.fold import fold_document
from kukai.ir.decompile.group_extract import (
    GroupExtraction,
    build_group_extract_cs,
    parse_group_index,
)
from kukai.ir.decompile.geom_extract import (
    GeometryArtifactProof,
    GeometryExtraction,
    build_geometry_extract_cs,
    extract_geometry,
    merge_geometry_extractions,
)
from kukai.ir.decompile.honesty import (
    BuildStatuses,
    EquivalenceClaim,
    EquivalenceScope,
)
from kukai.ir.decompile.lift_cache import cached_lift_document_detailed
from kukai.ir.decompile.name import name_document
from kukai.ir.decompile.passport import build_passport, passport_bytes
from kukai.ir.decompile.schema import EXTRACT_TIMEOUT_MS, L0Document
from kukai.ir.decompile.sketch_extract import (
    ProfileExtraction,
    build_sketch_extract_cs,
    extract_sketch_profiles,
)
from kukai.ir.decompile.verify import verify_document


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
        from kukai.ir.decompile.extract import _unwrap_bridge_payload

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
    # §18.4: пометка заражения. Читалась ли модель заведомо неполно (закрытые
    # рабочие наборы) — свойство ПРОГОНА, а не деталь L0: любой, кто держит в
    # руках run.json, обязан видеть её, не разбирая заголовок JSONL.
    is_partial_read: bool = False
    worksets_closed: int = 0
    # §18.1: четыре числа закона печатаются ЯВНО, а не выводятся читателем.
    # ``census`` — сводка decompile.census.CensusBalance.to_dict(); ops/atoms
    # доезжают сюда же, чтобы run.json нёс всё тождество целиком, а не его
    # половину, дописанную из паспорта.
    census: dict[str, Any] = field(default_factory=dict)
    ops_lifted: int = 0
    atoms: int = 0
    # §18.2: агрегат квитанций боковых индексов. Собирался, сливался,
    # сохранялся — и не читался НИКЕМ (M5 аудита 28.07): стена, чью дугу срезал
    # бюджет, поднималась хордой и попадала в статистику как успех. Здесь он
    # доезжает до того же файла, в котором лежат проценты, — чтобы прочитать
    # процент и не увидеть срезы стало невозможно.
    side_failures: dict[str, Any] = field(default_factory=dict)
    # ДЛИТЕЛЬНОСТЬ ПРОГОНА. Её не было НИ В ОДНОМ из 78 слепков на диске:
    # run.json нёс `elements_total`, паспорт и отпечаток ревизии — а сколько
    # это заняло, приходилось угадывать по временам файлов, и на резюме
    # угадывание давало 69 часов там, где работы был час.  I4 разрешает
    # время в метаданных прогона (запрещено оно в детерминированных
    # артефактах — L0 и программах), и живёт оно ровно здесь.
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
            "is_partial_read": self.is_partial_read,
            "worksets_closed": self.worksets_closed,
            "ops_lifted": self.ops_lifted,
            "atoms": self.atoms,
            **dict(self.census),
            **dict(self.side_failures),
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
    # §18.4: статус — первое, что видит оператор во время прогона; неполнота
    # чтения обязана быть видна ДО того, как появится паспорт с процентами.
    is_partial_read: bool = False
    worksets_closed: int = 0
    # §18.1: непрочитанное видно ВО ВРЕМЯ прогона, а не только в паспорте
    # после него — по той же причине, по какой там же оказалась пометка
    # частичного чтения.
    census: dict[str, Any] = field(default_factory=dict)
    # §18.2: срезы видны ВО ВРЕМЯ прогона, а не только в паспорте после него —
    # по той же причине, по какой там же оказалась пометка частичного чтения.
    side_failures: dict[str, Any] = field(default_factory=dict)
    # ── ПРИБОР ВРЕМЕНИ ───────────────────────────────────────────────────
    # Длительность стадии в мс, ключ — имя стадии. Пишется ПО ЗАВЕРШЕНИИ
    # стадии, поэтому идущая стадия в словаре отсутствует, а не стоит нулём:
    # «ещё идёт» и «прошла мгновенно» обязаны отличаться.
    stage_ms: dict[str, float] = field(default_factory=dict)
    # Покатегорийная/постадийная разбивка моста и нашей стороны —
    # см. extract._TIMING_KEYS о том, где проходит граница замера.
    timing_extract: dict[str, Any] = field(default_factory=dict)
    timing_sides: dict[str, Any] = field(default_factory=dict)
    #: monotonic-отметка старта прогона; настенного времени в ней нет.
    started_at: float = field(default_factory=time.monotonic)

    def timing_dict(self) -> dict[str, Any]:
        """Собрать раздел ``timing`` для status.json/run.json.

        ГРАНИЦА ОБЪЯВЛЕНА ЗДЕСЬ ЖЕ, В САМОМ АРТЕФАКТЕ (`boundary`), а не
        только в докладе: прибор, чей охват известен лишь автору, — это
        прибор на часть диапазона, и читатель вправе принять его за полный.
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
            "is_partial_read": self.is_partial_read,
            "worksets_closed": self.worksets_closed,
            **dict(self.census),
            **dict(self.side_failures),
            # Длительность видна ВО ВРЕМЯ прогона, а не только в run.json
            # после него: «сколько уже идёт и куда ушло» — первый вопрос
            # оператора на сороковой минуте, и отвечать на него размером
            # файла мы уже пробовали.
            "timing": self.timing_dict(),
            "updated_at": time.time(),
        }


# ── atomic JSON persistence (mirrors extract._atomic_write_json) ─────────────
def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


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
    """Тяжёлый СИНХРОННЫЙ шаг исполняется вне потока цикла событий.

    ЖИВОЙ ЗАМЕР 30.07, из-за которого это появилось. Во время выемки башни
    ``/health`` не ответил двенадцать раз подряд, по 25 секунд каждый, — а
    минутой раньше отвечал за 2 мс. Бэкенд поднят ОДНИМ воркером
    (``uvicorn --workers 1``), и пока конвейер материализовал 88 МБ L0, парсил
    18 МБ бокового индекса, лифтил, сворачивал и сериализовал паспорт, сервер
    не отвечал НИКОМУ: чат-сокеты не получали ответа на пинг и отваливались с
    ``close_code=1006`` (62 обрыва за 12 часов у десяти разных устройств), HTTP
    висел. Жалоба звучала как «нет нет да сервер отлетает»; на деле это было
    каждый раз, когда кто-то запускал разбор.

    Что это даёт и чего НЕ даёт. Шаг остаётся CPU-bound питоном и держит GIL,
    поэтому поток НЕ ускоряет разбор и не считает параллельно. Он даёт ровно
    одно: интерпретатор отпускает GIL каждые несколько миллисекунд
    (``sys.setswitchinterval``), цикл событий получает управление и успевает
    ответить на пинг. Цель — ОТЗЫВЧИВОСТЬ, а не производительность, и путать
    их не надо.

    Executor принадлежит ОДНОМУ шагу. Это не косметика: callback завершившегося
    worker в некоторых поддерживаемых Python/runtime boundary не будит
    selector event loop; ``run_in_executor`` тогда навсегда ждёт уже готовый
    результат. У pipeline несколько последовательных offload, поэтому это
    превращает успешный шаг в зависший прогон без typed outcome. Мы опрашиваем
    concurrent future коротким async-таймером: event loop остаётся отзывчивым,
    а корректность не зависит от межпоточного wakeup. Однозадачный executor
    также даёт каждому переходу собственный lifecycle; при отмене ``wait=False``
    не блокирует event loop, завершённый worker закрывается синхронно.
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
    """Замерить одну стадию и записать её длительность в состояние.

    Записывает и при исключении: стадия, упавшая на сороковой минуте, стоила
    сорок минут, и потерять их значит потерять самый дорогой замер прогона.
    Повторный вход в ту же стадию (резюм, ретрай) СУММИРУЕТСЯ — ключ хранит
    работу, а не последнюю попытку.
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
    """Заводит часы вокруг УЖЕ созданной корутины — обёртка без переноса кода.

    Нужна там, где стадия — одно многострочное выражение (``_offload`` хвоста):
    ``with`` потребовал бы переотступить весь вызов, а diff обязан оставаться
    читаемым. Время записывается и при исключении: упавший лифт стоил столько
    же, сколько успешный.
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

    Проба обязана считать ТОТ ЖЕ документ, что и стадия, которую она
    сторожит. Проба по хозяину вокруг стадии, читающей связь, — не ложное
    срабатывание, а СТОРОЖ БЕЗ ПРЕДМЕТА: она согласится сама с собой при
    любой правке внутри связи, и «модель не менялась» окажется утверждением о
    чужом документе.
    """
    from kukai.ir.decompile.extract import _execute_with_retries, _parse_probe
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

    ``link_title`` — ЧЕЙ документ читают все стадии разом. Он здесь, а не в
    каждом вызове, ровно по той причине, по которой стадии его вообще
    получили: один слепок — один документ, и стадия, забытая при раздаче,
    молча читала бы хозяина (замер 30.07: 1837 квитанций у одной стадии и 20
    чужих строк у неё же).

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
        # Оформление — страничная стадия наравне с прочими: 13 905 размеров
        # и 2 697 примечаний одной полномодельной пробой были бы той же
        # монеткой, из-за которой sketch переехал в страничные.
        "annotation": lambda ids: build_annotation_extract_cs(
            list(ids), link_title=link_title),
        # Принадлежность системе: без неё инженерное здание не пересобрать
        # (сухой прогон Snowdon 30.07 — 0/26 чанков).
        "mep_system": lambda ids: build_mep_system_extract_cs(
            list(ids), link_title=link_title),
        # МАРКИ — ЕДИНСТВЕННАЯ стадия, чей C# ЗАВИСИТ ОТ ВЕРСИИ Revit.
        # У цели марки нет ни одного члена, живущего во всех шести версиях
        # (TaggedLocalElementId удалён после 2022, GetTaggedLocalElementIds
        # отсутствует в 2021), поэтому версия приезжает сюда из прочитанного
        # документа (``Application.VersionNumber``), а не угадывается.
        # Аргумент необязателен ровно затем, чтобы вызов без него — а он
        # есть в тестах контракта — по-прежнему перечислял стадии.
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
    # Потолок и ограждения дописаны 29.07 волной ЗАХВАТА. Повод не в том, что
    # появились операции (они приехали днём раньше), а в том, что операциям
    # было НЕЧЕМ питаться: на К2 все 81 потолок и все 203 ограждения лежали
    # bbox_only с пустым params и не встречались НИ В ОДНОМ боковом индексе.
    #
    # Строка и коллекторы в sketch_extract.py обязаны двигаться ВМЕСТЕ:
    # категория здесь без коллектора там ⇒ каждый id уходит квитанцией
    # element_unresolved (класс CUT) и раздувает срез на ровном месте;
    # коллектор там без строки здесь ⇒ id никогда не запрашиваются, __skAccept
    # их отсекает, и стадия молча не читает ничего.
    "sketch": frozenset({
        "OST_Floors", "OST_Roofs", "OST_Stairs",
        "OST_Ceilings", "OST_StairsRailing", "OST_Railings",
    }),
    # Носителей витражной сетки три рода (стена, витражная система, кровля).
    # OST_CurtaSystem дописан в таблицу категорий extract.py (хвост волны
    # aaa44b45, 28.07) — теперь и здесь все три рода, конвейер кормит их
    # стадию id-ами наравне со стеной и кровлей.
    "curtain": frozenset({"OST_Walls", "OST_Roofs", "OST_CurtaSystem"}),
    # Категории оформления держит СВОЙ модуль (annotation_extract), а не
    # список здесь: строка в таблице и коллектор в съёмщике обязаны ходить
    # парой, и единственный способ это гарантировать — один источник.
    "annotation": ANNOTATION_CATEGORIES,
    "mep_system": MEP_SYSTEM_CATEGORIES,
    # Десять родов марок держит СВОЙ модуль (tag_extract) по той же причине,
    # что и оформление: строка в таблице и коллектор в съёмщике обязаны
    # ходить парой, и единственный способ это гарантировать — один источник.
    "tag": TAG_CATEGORIES,
    # Категории, чьи элементы суть ЭКЗЕМПЛЯРЫ СЕМЕЙСТВ. Без строки в боковом
    # индексе такой элемент не поднимется никогда: лифт узнаёт из него и вид
    # размещения, и точку, и кривую, и флипы.
    #
    # ЗАМЕР 28.07: после того как экстрактор научился видеть разделы, ЭОМ дал
    # 2546 элементов вместо 1916 — и 354 из новых стали атомами с одной
    # причиной «element is absent from the family placement side index».
    # Категорию добавили в чтение, а в индекс — нет: раздел стал ВИДЕН, но
    # по-прежнему невыразим.
    #
    # Индекс закрыт по построению (не-FamilyInstance строк не порождает),
    # поэтому лишняя категория здесь безвредна, а недостающая — теряет
    # элементы молча.
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
        # РД, 29.07: та же ловушка, что описана выше, поймана ДО того, как
        # стоила элементов. Волна расширения таблицы чтения (54 → 73
        # категории) добавила в extract.py два рода, чьи элементы суть
        # экземпляры семейств: элементы узлов и телефонные устройства
        # (замер 13A-RD-AR-K2_v33: 3046 + 4479 = 7525 штук). Без строки
        # здесь они стали бы видны чтению и невыразимы лифтом — ровно те
        # «absent from the family placement side index», которыми ЭОМ
        # заплатил 28.07.
        "OST_DetailComponents", "OST_TelephoneDevices",
    }),
    "group": frozenset(),
}

# Stages whose request set is produced by an earlier compiler stage rather
# than selected from a static L0 category table.
_DYNAMIC_STAGE_IDS = frozenset({"geometry"})


def _ids_for_stage(document: L0Document, stage: str) -> list[str]:
    """Select L0 element ids for one side-index stage (I1 — data-driven)."""
    selection = _STAGE_CATEGORIES.get(stage)
    if not selection:
        return []
    return [e.element_id for e in document.elements if e.category in selection]


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
    from kukai.ir.decompile.extract import (
        EXTRACT_RETRIES, _WindowWaitBudget, _execute_awaiting_window)

    # Боковые стадии ходили в мост БЕЗ ретраев и без ожидания окна
    # (`retries=0`), и первая же сетевая икота их убивала: замер 29.07 на К2
    # РД — стадия кривых умерла «after 1 attempts: TimeoutError» сразу после
    # извлечения 55 293 элементов, когда UI-поток Revit ещё не отдышался.
    # Дисциплина страниц категорий (#26) распространяется сюда без оговорок:
    # чтения идемпотентны, каждое под ревизионным стражем.
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
            # СЧЁТЧИК НАРУШЕНИЙ УЖЕ МЕРИЛ ЭТО ВРЕМЯ И ВЫБРАСЫВАЛ ЕГО.
            # `slo_violations` считал пересечения порога и терял саму
            # длительность: «три нарушения» не отличить от «три раза по
            # 21 секунде» и от «три раза по девять минут». Замер тот же,
            # цена та же — теперь он ещё и сохраняется.
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
            # §18.2: стадия сверяет ЗАПРОШЕННОЕ с ПОЛУЧЕННЫМ прямо здесь, на
            # своей пачке — потерянный id называется поимённо, а не всплывает
            # через две стадии дырой в покрытии. Полномодельные стадии (group)
            # заказа не делают, сверять там нечего.
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
        # One automatic retry (Д2) before failing closed.  Часы той же
        # стадии заводятся ВТОРОЙ раз и суммируются: повтор — это работа,
        # которую прогон действительно проделал, а не бесплатная оговорка.
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
    # Стадия УЖЕ страничная (_SIDE_BATCH = 200), и «в одном вызове» из старого
    # комментария перестало быть правдой ещё в волне бюджетов. Отсюда закон
    # этой функции: КАЖДЫЙ кортеж ProfileExtraction обязан быть здесь
    # перечислен. Забытое поле не падает и не шумит — оно уцелевает на
    # однопакетном тесте и молча пропадает на настоящем здании, где пакетов
    # больше одного. Ровно так исчезли бы пути ограждений на К2 (543 строки
    # эскизов + 81 потолок + 203 ограждения — это заведомо не один пакет).
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

    MINOR-10 (аудит 28.07): раньше неузнанная форма ответа возвращала ``[]`` —
    и это было хуже, чем кажется. Пустой индекс писался на диск как валидный
    артефакт (``_is_valid_artifact`` смотрит только на размер файла), а
    resume-логика на следующем прогоне ПЕРЕИСПОЛЬЗОВАЛА его вместо
    перечитывания: одна невнятная полезная нагрузка навсегда стирала стадию
    из разбора. §18.2 требует квитанции даже на «неузнанную форму ответа», а
    квитанция на весь ответ — это типизированный отказ стадии.
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
    """Список квитанций из ответа моста; отсутствие ключа — пустой список.

    Ключ ``failures`` обязателен по §18.2 для НОВЫХ эмиттеров; здесь он мягкий
    ровно настолько, чтобы конвейер не падал на чужом/старом ответе — потерю
    элементов всё равно поймает сверка счётчиков стадии, и поймает адресно.
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
    """Одна пачка family_placement: строки + квитанции, обе половины ответа."""
    return FamilyPlacementExtraction.from_rows(
        _rows_of(payload, "placements"),
        wire_failures=_wire_failures_of(payload))


def _group_part(payload: Any) -> GroupExtraction:
    """Одна пачка group: строки + квитанции."""
    return GroupExtraction.from_rows(
        _rows_of(payload, "groups"),
        wire_failures=_wire_failures_of(payload))


def _accounted_ids(part: Any) -> list[str]:
    """id, о которых пачка что-то СКАЗАЛА — строкой или квитанцией."""
    ids: list[str] = []
    for record in getattr(part, "records", ()) or ():
        # ``record_element_id``, а не ``record.element_id``: у витражной
        # строки поле называется ``wall_id``, и прямое чтение объявило бы
        # потерянным каждый УСПЕШНО прочитанный витраж.
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
    """Тонкая обёртка над общим валидатором — чтобы её было легко подменить."""
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


# ── счётчик строк бокового артефакта (§18.2, MINOR-10) ──────────────────────
#
# «Артефакт, переиспользуемый resume-логикой, несёт счётчик строк для сверки
# при переиспользовании». Счётчик живёт в ОДНОМ манифесте прогона, а не внутри
# каждого из пяти индексов: класть его внутрь значило бы поменять схему всех
# пяти (три из них — замороженные форматы с точной сверкой полей) ради числа,
# которое описывает не индекс, а ПРОГОН, его записавший. Манифест лежит рядом
# с индексами, пишется атомарно тем же прогоном и читается на resume.
#
# Отсутствие записи о стадии — не отказ, а «не измерялось»: разборы, снятые до
# этой волны, манифеста не имеют, и объявлять их непереиспользуемыми значило бы
# требовать полного перечитывания архива ради формы (та же осознанная миграция,
# что у полей рабочих наборов в §18.4).
def _side_counts(extraction: Any) -> dict[str, int]:
    return {
        "rows": len(getattr(extraction, "records", ()) or ()),
        "failures": len(getattr(extraction, "failures", ()) or ()),
    }


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
    # ЧЕЙ документ читала ЭТА стадия. Счётчик строк ловит подменённый
    # артефакт, но НЕ ловит артефакт, снятый с другого документа: у него и
    # схема та же, и строк вполне может быть столько же.
    #
    # Источник пишется У КАЖДОЙ СТАДИИ, а не один на каталог: стадии
    # пересчитываются по очереди, и общая запись, обновлённая первой из них,
    # объявила бы «наши» ещё не тронутые чужие индексы остальных.
    stage_manifest: dict[str, Any] = {
        **_side_counts(extraction), "source": link_title}
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
    """Можно ли переиспользовать уже лежащий индекс стадии.

    Две разные проверки, и вторая появилась 30.07 вместе с чтением связей.
    Счётчик строк ловит ПОДМЕНЁННЫЙ артефакт. Он не ловит артефакт, снятый с
    ДРУГОГО ДОКУМЕНТА: у индекса хозяина ровно та же схема и вполне может быть
    ровно столько же строк, сколько у индекса связи. Каталог
    ``snowdon_elec_v1`` — живой тому пример: его индексы сняты с заказом от
    связи, а прочитаны у хозяина, и по счётчику они безупречны.

    Каталог, снятый ДО этой волны, источника не записал. Пока спрашивают
    хозяина, это ничего не меняет (прежнее поведение). Но если спрашивают
    СВЯЗЬ, «неизвестно чей» — это не «наверное наш»: стадия пересчитывается.
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
        # §18.4: процент, вычисленный на частичном чтении, печатается ТОЛЬКО
        # вместе с пометкой — и раньше процентов, а не сноской под ними.
        lines.append(
            "- ⚠ ЧАСТИЧНОЕ ЧТЕНИЕ: рабочих наборов закрыто "
            f"{stats.get('worksets_closed', '?')} — цифры ниже описывают "
            "видимую часть модели, а не модель")
    # §18.1: перепись — ПЕРЕД процентами. Читатель обязан узнать, каков
    # знаменатель, раньше, чем увидит числитель; порядок здесь и есть закон.
    summary = stats.get("census_summary_ru")
    if summary:
        lines.append(f"- перепись: {summary}")
    unscanned = stats.get("unscanned_by_category")
    if isinstance(unscanned, Mapping):
        # Весь ``top`` целиком: остаток ниже посчитан от границы top-N, и
        # срез из среза уронил бы строки в щель между показанным и «прочими».
        for row in unscanned.get("top", []):
            lines.append(
                f"  - {row.get('category')}: не читалось "
                f"{row.get('unscanned')} ({row.get('reason')})")
        if unscanned.get("other_categories"):
            lines.append(
                f"  - прочие {unscanned['other_categories']} категорий: "
                f"не читалось {unscanned.get('other_elements', '?')}")
    # §18.2: строка квитанций стоит СРАЗУ ЗА переписью и ПЕРЕД процентами.
    # Перепись отвечает «чего мы не смотрели вовсе», квитанции — «что мы
    # смотрели и не досмотрели», и только после обоих ответов процент значит
    # то, что о нём думает читатель.
    receipts = stats.get("side_cuts_summary_ru")
    if receipts:
        lines.append(f"- квитанции срезов: {receipts}")
        by_stage = stats.get("side_failures_by_stage")
        if isinstance(by_stage, Mapping) and by_stage:
            # По стадиям печатается РАЗБИВКА «срезано + отвечено», а не одна
            # сумма. Сумма читалась как масса отказов: на 13A-RD-AR-K2_v33
            # строка «curtain 14343» была самым большим числом паспорта, тогда
            # как срезов там 19, а 14 324 — ответы «стена не витражная», у
            # каждого из которых есть ещё и полноценная строка индекса.
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


# ── the run ──────────────────────────────────────────────────────────────────
async def run_decompile(
    executor: BridgeExecutor,
    *,
    out_dir: str | os.PathLike[str],
    change_stamp: str,
    status_cb: Optional[StatusCallback] = None,
    cs_builders: Optional[Mapping[str, SideCsBuilder]] = None,
    timeout_ms: int = EXTRACT_TIMEOUT_MS,
    #: Снимать не хозяина, а его СВЯЗЬ с таким Document.Title. Слепок
    #: отдельный, со своим штампом. Источник доводится до КАЖДОЙ боковой
    #: стадии и до пробы Д2 вокруг неё: один слепок — один документ.
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

        # ОДИН запас ожидания окна на весь прогон: извлечение и боковые
        # стадии тратят его сообща. Иначе мёртвое окно стоило бы по потолку
        # каждой стадии, и «пять минут один раз» превратилось бы в полчаса.
        from kukai.ir.decompile.extract import _WindowWaitBudget
        window_budget = _WindowWaitBudget()

        # САМАЯ ДЛИННАЯ СТАДИЯ ОБЯЗАНА НАЗЫВАТЬ СЕБЯ. Замер 30.07 на живой
        # башне: чтение шло 41 минуту, L0 дорос до 88 МБ, а status.json всё
        # это время утверждал `stage=open_model_profile, done 0/0` — стадия
        # выставлялась ДО чтения и больше не трогалась. Отличить «идёт
        # нормально» от «повисло» можно было только по размеру файла, то есть
        # никаким инструментом.
        state.stage = "extract"
        state.done = 0
        state.total = 0
        _write_status(state, status_cb)

        def _extract_progress(progress: Any) -> None:
            # done/total здесь считаются в КАТЕГОРИЯХ, у боковых стадий — в
            # партиях. Оба честны, пока стадия названа рядом: смысл счётчика
            # задаёт `stage`, и путать их — та же ошибка, что путать
            # знаменатели покрытия.
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
        # РАЗБИВКА ИЗВЛЕЧЕНИЯ ДОЕЗЖАЕТ ДО run.json. Держать её только в
        # чекпойнте значило бы: чтобы узнать, куда ушёл час, надо знать про
        # существование служебного файла резюма. Итог — рядом с процентами,
        # покатегорийные строки остаются в чекпойнте.
        from kukai.ir.decompile.extract import _timing_totals
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
        # §18.4: пометка поднимается СРАЗУ после материализации — до боковых
        # индексов, лифта и любого процента. Замер 27.07: 17 закрытых наборов
        # из 18 дали 11 элементов вместо 2016 при всех статусах complete.
        state.is_partial_read = document.is_partial_read
        state.worksets_closed = document.worksets_closed
        # §18.1: бухгалтерия документа сводится СРАЗУ после материализации —
        # до боковых индексов, лифта и любого процента. Расхождение тождества
        # (извлечено больше, чем есть в документе) — типизированная ошибка
        # прогона, а не строчка в логе: утверждение «прочитано N» опровергнуто
        # переписью, и всё, что построено дальше, стояло бы на нём.
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

        # ВЕРСИЯ REVIT СТАНОВИТСЯ ИЗВЕСТНА ТОЛЬКО ЗДЕСЬ. Строители C#
        # собираются до чтения (документа ещё нет), а стадии марок нужна
        # версия: её поверхность рвётся на 2022, и одно тело на шесть целей
        # не собралось бы либо на 2021, либо на 2023+.
        #
        # ДВА УСЛОВИЯ, И ОБА ПРОВЕРЕНЫ ПО СОБРАННОМУ НАБОРУ, А НЕ ПО ФАБРИКЕ.
        # ``"tag" in builders`` — стадию перепривязывает только тот, кто её
        # уже зарегистрировал: подменённая фабрика вправе стадию НЕ давать, и
        # тогда честный ответ — пропуск, а не воскрешение. Второе условие —
        # чужой строитель всегда сильнее умолчания.
        #
        # Фабрика здесь намеренно НЕ вызывается второй раз: она уже отдала
        # ВОСЕМЬ стадий, и второй вызов ради ОДНОЙ переизготовил бы семь
        # чужих. Строитель собирается тем же выражением, что и в фабрике, —
        # прямо из ``build_tag_extract_cs``, и ИСТОЧНИК пересобранная марка
        # уносит с собой: стадия, потерявшая его на перепривязке, читала бы
        # хозяина ровно там, где остальные семь читают связь.
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
        mep_systems = await _side_or_resume(
            guarded_executor, document, "mep_system",
            extract_mep_systems, merge_mep_systems,
            builders, state, status_cb,
            directory / "mep_system.index.json",
            MepSystemExtraction, timeout_ms=timeout_ms,
            window_budget=window_budget, link_title=link_title)

        if _read_cancel(directory):
            return _cancelled(state, status_cb)

        # §18.2: агрегат квитанций собирается СРАЗУ после боковых стадий — до
        # лифта и до любого процента, чтобы «сколько мы недосмотрели» было
        # известно раньше, чем «сколько мы подняли».
        side_products: dict[str, Any] = {
            "curve": curve,
            "sketch": profiles,
            "curtain": curtain,
            "family_placement": family,
            "group": groups,
            "annotation": annotations,
            "tag": tags,
            "mep_system": mep_systems,
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
            # Индекс кривых собран выше (round-trip в мост + curve.index.json) и
            # раньше здесь ТЕРЯЛСЯ: дуговые стены поднимались хордой, тогда как
            # A5-релифт тот же индекс передаёт — оригинал видел меньше контекста,
            # чем пересобранная сторона, и сверка шла на деградированном
            # представлении (арх-разбор 2026-07-25 §3.3).
            wall_curve_index=curve,
            # Индекс витражей — то же самое одной волной позже: без него
            # ячейка витража невыразима, и панели остаются атомами (дизайн
            # 2026-07-28).
            curtain_index=curtain,
            # Оформление: без этого индекса каждое примечание остаётся
            # честным атомом source_contract_gap — ровно как до волны.
            annotation_index=annotations,
            # Без этого индекса каждая марка остаётся честным атомом
            # source_contract_gap — ровно как до волны.
            tag_index=tags,
            mep_system_index=mep_systems,
            enabled=True,
            cache_dir=str(directory / "lift_cache"),
        ))
        l1_nodes = lift_result.nodes

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
        manifest = await _timed(state, "verify",
            _offload(build_dependency_manifest, document))
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
        # §18.4: проценты паспорта считаются по тому, что УВИДЕЛИ. Пометка
        # частичного чтения кладётся в ту же секцию, что и проценты, — чтобы
        # её нельзя было прочитать отдельно от них.
        passport = passport.to_dict()
        ops_lifted = int(passport["stats"].get("ops_lifted") or 0)
        passport["stats"] = {
            **passport["stats"],
            "is_partial_read": document.is_partial_read,
            "worksets_closed": document.worksets_closed,
            # §18.1: знаменатель. ``lifted_pct_extracted`` — историческая база
            # (от прочитанного), ``lifted_pct_document`` — база документа.
            # Обе печатаются вместе намеренно: одна отвечает на вопрос «как
            # хорош компилятор на том, что он видит», другая — «какая часть
            # здания вообще выражена», и подменять вторую первой значит
            # называть свойством компилятора свойство таблицы категорий.
            **balance.to_dict(),
            "census_summary_ru": balance.summary_ru(),
            # §18.2: квитанции стоят в ОДНОЙ секции с процентами по той же
            # причине, что и пометка частичного чтения, — прочитать процент,
            # не увидев срезов, не должно получаться.
            **side_failures,
            "side_cuts_summary_ru": receipts_summary_ru(side_failures),
            "lifted_pct_extracted": balance.extracted_pct(ops_lifted),
            "lifted_pct_document": balance.document_pct(ops_lifted),
        }
        (directory / "passport.json").write_bytes(passport_bytes(passport))
        passport_md = directory / "passport.md"
        passport_md.write_text(_passport_markdown(passport), encoding="utf-8")

        # tree/named artifacts for downstream waves.  ``tree`` and NAME's tree
        # are already JSON-shaped TypedDicts — persist them directly.
        _atomic_write_json(directory / "tree.json", tree)
        named_tree = name_result.get("tree")
        if isinstance(named_tree, Mapping):
            _atomic_write_json(directory / "named.json", named_tree)

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
            is_partial_read=state.is_partial_read,
            worksets_closed=state.worksets_closed,
            census=balance.to_dict(),
            ops_lifted=ops_lifted,
            atoms=int(passport["stats"].get("atoms") or 0),
            side_failures=side_failures,
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
        # НАШ дефект, а не молчание окна и не отказ Revit. Отдельный код
        # нужен затем, что читатель отчёта по нему решает, КУДА смотреть:
        # «extract_failed» отправлял в Revit, где всё было в порядке.
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
        # §18.2: стадия потеряла заказанные id и не оставила о них квитанции.
        # Это ОТКАЗ ПРОГОНА, а не предупреждение: всё, что построено дальше,
        # стояло бы на утверждении «столько-то элементов не выражается», а на
        # деле их не читали.
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
        # §18.2/MINOR-10: артефакт переиспользуется только если его содержимое
        # совпадает со счётчиком, записанным прогоном, который его сделал.
        # Иначе на диске могла остаться (и раньше оставалась) пустая, но
        # синтаксически валидная стадия — и она подменяла собой чтение молча.
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
        is_partial_read=state.is_partial_read,
        worksets_closed=state.worksets_closed,
        # §18.1: неуспешный прогон обязан унести те же числа. Прогон, упавший
        # ИЗ-ЗА тождества, без них не объяснить, а прогон, упавший позже, —
        # не оценить.
        census=dict(state.census),
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
        is_partial_read=state.is_partial_read,
        worksets_closed=state.worksets_closed,
        # §18.1: неуспешный прогон обязан унести те же числа. Прогон, упавший
        # ИЗ-ЗА тождества, без них не объяснить, а прогон, упавший позже, —
        # не оценить.
        census=dict(state.census),
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
