"""Wave A5 — live idempotence: «decompile → rebuild reproduces the building».

The northern star of the KIR compiler.  This orchestrator measures whether a
model's decompiled leaves, materialized at a Δ-offset and rebuilt into the LIVE
copy, re-extract and re-lift to EXACTLY the Δ-translated originals — proving the
decompile/rebuild round trip is faithful, not merely compilable.

Mechanics (pinned by the master design, do not drift):

1.  Run on the SAME model at Δ = (200000, 0, 0) mm (within Revit's ±16 km
    coordinate extent).  A translation is exact by construction on the CANON_MM
    grid, and the canon (merkle) is translation-invariant, so the Δ-translated
    originals are the ground truth the rebuild must reproduce.
2.  ``decompile M`` (already persisted by ``pipeline.run_decompile``) → materialize
    op-leaves at Δ (``materialize.leaves_to_program(offset_mm=Δ)``) → rebuild
    per-op against the live bridge → collect created ElementIds from the witness
    read-backs → re-extract ONLY those ids (``reextract.build_reextract_cs``) →
    re-lift → compare ``multiset_hash(re-lift)`` with
    ``multiset_hash(translate(originals, Δ))``.
3.  Report: per-op-kind exact %, discrepancies listed.
4.  Cleanup: delete the collected ids (``allow_destructive``, chunked) in a
    ``finally`` — a cleanup failure that leaves orphaned Δ-elements is
    inadmissible, so cleanup outcome is a first-class field of the result.
5.  Dashboard metric: last run, exact %, date.

Д3 safety (this is the heart of the wave — built fail-closed):

* The LIVE path writes to a live model.  It is refused unless
  ``serving.revit_decompile_enabled()`` (flag ``KUKAI_KIR_DECOMPILE=stage2`` AND
  the admin device) AND ``doc.Title`` is confirmed a COPY via
  :class:`SafetyContext` (allowlist substring or an explicit confirm token).  By
  default — no confirmation — the live path REFUSES; it never runs.
* Datums (``create_level`` / ``create_grid``) are NOT rebuilt (their names are
  unique; a rebuild would collide and produce false refusals).  Levels/grids are
  pinned by their EXISTING ElementIds (the materializer already skips datum ops
  and every other op references the existing datum by id).  The comparison counts
  only NON-datum ops.
* The report separates ``raw_exact_pct`` from ``adjusted_exact_pct`` (raw minus
  the EXPECTED discrepancy classes — rooms outside their enclosure, context
  dependent types, etc.) so the exact % never lies.

Offline boundary (this module): everything except the live bridge round trips is
pure and deterministic — no clock, no random, no unordered iteration.  The bridge
executor and ``rebuild_program``/``delete_program`` runners are injected; tests
drive them with realistic witness read-backs through the real parsers.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter, defaultdict
from typing import (Any, Awaitable, Callable, Iterable, Mapping, Optional,
                    Protocol, Sequence)

from kukai.ir import spec
from kukai.ir.decompile.component import _translate_leaf
from kukai.ir.decompile.fold import (
    FIDELITY_CANON_VERSION,
    FidelityCanon,
)
from kukai.ir.decompile.l1_schema import L1Node, _node_refs
from kukai.ir.decompile.geom_extract import GeometryExtraction
from kukai.ir.decompile.geometry_acceptance import (
    FormAcceptanceState,
    check_form_acceptance,
)
from kukai.ir.decompile.materialize import (
    _DATUM_OPS,
    _op_id,
    leaves_to_program,
)
from kukai.ir.decompile.reextract import (
    REEXTRACT_BATCH,
    ReExtractError,
    build_reextract_cs,
    build_room_reextract_cs,
    parse_reextract_rows,
    parse_room_reextract,
    reextracted_document,
)
from kukai.ir.decompile.schema import L0Document

from kukai.ir.idempotence_contract import (
    DELTA_MM,
    REBUILD_PLAN_VERSION,
    IdempotenceError,
    SafetyContext,
    Vec3,
    _ORIGIN,
)

# Deletes go out in bounded chunks so cleanup never emits a 10k-op program; the
# authoring envelope caps programs at 20 ops (spec) so a chunk stays well under.
_DELETE_CHUNK = 16

# Потолок чанкового fail-soft. Выше него прогон отказывает целиком: доля
# модели, построенная поверх четверти отказов, — уже не «процент качества
# компилятора», а процент от неизвестно чего. Порог проверяется И по числу
# чанков, И по числу опов (см. врезку в run_idempotence: одно из двух чисел
# всегда врёт — solo-чанк несёт один оп, большой до 250).
MAX_REFUSED_CHUNK_SHARE = 0.25

# EXPECTED discrepancy classes (Д3b).  These op-kinds legitimately fail to
# reproduce their exact translated leaf even on a faithful rebuild, so their
# mismatches are SUBTRACTED from the adjusted %.  Each entry documents WHY.
EXPECTED_DISCREPANCY_OPS: dict[str, str] = {
    # A room is defined by its bounding walls; its geometry is a CONSEQUENCE of
    # the enclosure Revit computes after the walls exist, not a stored input, so
    # a re-lifted room boundary need not match the translated original exactly.
    "create_room": "room geometry is enclosure-derived, not a stored input",
    # A point foundation's variety-dependent instance state is likewise not fully
    # captured by L0 1.0 (mirrors verify._fidelity_assessment's carve-out).
    "create_foundation": "point-foundation instance state is context-dependent",
    # place_family REMOVED 2026-07-21: its canon is exactly {xyz, rotation,
    # mirrored/hand/facing, symbol, level} — all reproduced (live floor-20
    # furniture, XOR-flip model + FacingFlipped guard).  Keeping it here hid
    # 15 real flip-guard misses under adjusted% (Goodhart).  A place_family
    # mismatch is now an HONEST bug, not a carved-out expectation.
}


# Immutable evidence values live below orchestration.  Re-export these names
# from the historical top-level module for API compatibility.
from kukai.ir.idempotence_report import (
    IdempotenceReport,
    KindComparison,
    MetricTotals,
    _ratio_pct,
    _round_pct,
)

# ── leaf partitioning + translated ground truth ──────────────────────────────


def _op_leaves(leaves: Sequence[L1Node]) -> list[L1Node]:
    """Non-datum op-leaves only (datums are pinned existing; atoms are skipped).

    An op whose ``ref`` points at a leaf this filter removed must go too, and
    so must anything that referenced IT — resolved to a fixed point. Otherwise
    the corpus carries a dangling reference and ``FidelityCanon`` refuses the
    whole run with ``fidelity ref target … is absent from graph``, which
    reaches the operator as a bare "internal" error.

    Observed 27.07 on SOB6.2: a ``create_door`` hosted on a wall whose location
    line is ``core_interior`` — the wall stayed an atom (not expressible by
    create_wall yet), the door did not, and the run died. It is the same law
    ``materialize.leaves_to_program`` already applies with its typed
    ``host_unmaterialized`` skip; an excluded host is data, never an exception.
    """

    kept = {
        leaf["_id"]: leaf for leaf in leaves
        if leaf["kind"] == "op" and leaf["op_name"] not in _DATUM_OPS
    }
    while True:
        orphaned = {
            node_id for node_id, leaf in kept.items()
            if any(ref not in kept for ref in _node_refs(leaf.get("params") or {}))
        }
        if not orphaned:
            return list(kept.values())
        for node_id in orphaned:
            del kept[node_id]


def _hosted_skipped_count(leaves: Sequence[L1Node]) -> int:
    """Ops dropped by :func:`_op_leaves` because their host is not rebuilt."""

    non_datum = sum(
        1 for leaf in leaves
        if leaf["kind"] == "op" and leaf["op_name"] not in _DATUM_OPS)
    return non_datum - len(_op_leaves(leaves))


def _datum_count(leaves: Sequence[L1Node]) -> int:
    return sum(
        1 for leaf in leaves
        if leaf["kind"] == "op" and leaf["op_name"] in _DATUM_OPS)


def _atom_count(leaves: Sequence[L1Node]) -> int:
    return sum(1 for leaf in leaves if leaf["kind"] == "atom")


def _translate_originals(op_leaves: Sequence[L1Node], delta: Vec3) -> list[L1Node]:
    """Δ-translated copies of the comparison leaves (the ground truth).

    Reuses ``component._translate_leaf`` — the SAME coordinate-field authority the
    materializer's ``offset_mm`` uses — so translated originals and materialized
    ops move by identical arithmetic (no second coordinate walk, no drift).
    """

    return [_translate_leaf(leaf, delta) for leaf in op_leaves]  # type: ignore[misc]


def _op_name_of(leaf: L1Node) -> str:
    return leaf["op_name"] if leaf["kind"] == "op" else "atom"


#: Эффект опа семейства ``modify`` не создаёт элемента: Revit сохраняет
#: element id, id не попадает в ``created_ids``, а переизвлечение спрашивает
#: РОВНО про ``created_ids``.  Такой эффект невидим ПО ПОСТРОЕНИЮ вселенной
#: сравнения — сколько лифт ни чини.
#:
#: Замерено на пересборке №6 (sob62_fas_r23_v11): 54 ожидаемых
#: ``set_curtain_panel``, из них 44 меняют тип ячейки НА МЕСТЕ и в
#: переизвлечении отсутствуют, а 10 элемент порождают и там ЕСТЬ.  Считать все
#: 54 недостачей — врать про 44; вынести все 54 — спрятать 10 (ровно так
#: карв-аут ``place_family`` прятал 15 живых промахов flip-guard, см. выше).
#: Поэтому правило проверяет НАБЛЮДАЕМОСТЬ, а не имя опа.
def _assigned_type_names(leaf: L1Node) -> set[str]:
    """Типы, которые лист НАЗНАЧАЕТ (селекторы ``{"by":…, "value":…}``).

    Структурно, а не по списку имён параметров: у ``set_curtain_panel`` это
    ``panel_type``, у будущих modify-опов — их собственные селекторы, и правило
    не придётся править вместе с реестром.
    """
    params = leaf.get("params")
    if not isinstance(params, Mapping):
        return set()
    out: set[str] = set()
    for value in params.values():
        if isinstance(value, Mapping) and "by" in value \
                and isinstance(value.get("value"), str):
            out.add(value["value"])
    return out


def modify_outside_universe(
    expected: Sequence[L1Node],
    reextracted_rows: Sequence[Mapping[str, Any]],
) -> list[int]:
    """Индексы ожидаемых листьев, чей эффект вселенной сравнения не виден.

    Лист попадает сюда, только если ОБА условия выполнены:
    1. его оп принадлежит семейству ``modify`` (правило из реестра, не список);
    2. в переизвлечении нет НИ ОДНОГО элемента, несущего назначаемый тип, —
       то есть эффект не породил элемента, попавшего в ``created_ids``.

    Второе условие и есть защита от сокрытия: ячейка, которая элемент ПОРОДИЛА,
    остаётся честной недостачей и видна как ``missing``.
    """
    # `spec` импортирован на уровне модуля (строка 56). Повторный локальный
    # импорт делал имя ЛОКАЛЬНЫМ на всю функцию — та же тень, что уронила
    # обработчик отказа через `json` (замер 02.08), — а try/except вокруг него
    # был мёртвой защитой: недоступный реестр не дал бы модулю загрузиться.
    present = {row.get("type_name") for row in reextracted_rows
               if isinstance(row, Mapping)}
    out: list[int] = []
    for idx, leaf in enumerate(expected):
        if leaf.get("kind") != "op":
            continue
        op = spec.OPS.get(leaf.get("op_name"))
        if op is None or op.family != "modify":
            continue
        if not (_assigned_type_names(leaf) & present):
            out.append(idx)
    return out


def _jsonable(value: Any) -> Any:
    """Индекс -> JSON, чем бы он ни был: дамп доказательства не вправе ронять
    прогон из-за незнакомого типа."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    for attr in ("to_dict", "as_dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:  # noqa: BLE001
                break
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    records = getattr(value, "records", None)
    if records is not None:
        return {"records": _jsonable(records)}
    if hasattr(value, "__dict__"):
        return {str(k): _jsonable(v) for k, v in vars(value).items()}
    return repr(value)


def _expected_discrepancy_reason(leaf: L1Node) -> Optional[str]:
    """Return the narrow, leaf-specific adjusted-metric carve-out reason."""

    if leaf["kind"] != "op":
        return None
    op_name = leaf["op_name"]
    if op_name == "create_room":
        return EXPECTED_DISCREPANCY_OPS[op_name]
    if op_name == "create_foundation":
        params = leaf.get("params")
        # Current lift emits ``isolated``; ``point`` remains accepted for old L1.
        if isinstance(params, Mapping) and params.get("variety") in {
                "isolated", "point"}:
            return EXPECTED_DISCREPANCY_OPS[op_name]
    return None


def _compare(
    expected: Sequence[L1Node],
    relifted: Sequence[L1Node],
    outside_universe: Sequence[int] = (),
) -> tuple[bool, str, str, list[KindComparison], list[dict[str, Any]]]:
    """Compare two leaf sets by canonical hash, overall and per op-kind.

    The overall verdict is the order-independent ``multiset_hash`` equality (the
    canonical Part 6.1 hash).  The per-kind tally matches canonical-hash multisets
    within each op-kind so a partial reproduction still yields an honest per-kind
    %.  A canonical hash present in ``expected`` but not matched in ``relifted``
    (accounting for multiplicity) is a discrepancy.
    """

    expected_leaf_hashes = FidelityCanon.hash_sequence(expected, _ORIGIN)
    actual_leaf_hashes = FidelityCanon.hash_sequence(relifted, _ORIGIN)
    expected_hash = FidelityCanon.multiset_digest(expected_leaf_hashes)
    actual_hash = FidelityCanon.multiset_digest(actual_leaf_hashes)
    match = expected_hash == actual_hash

    # Bucket re-lifted canonical hashes for multiset matching within a kind.
    relift_pool: dict[str, Counter[str]] = defaultdict(Counter)
    relift_leaves: dict[str, dict[str, list[L1Node]]] = defaultdict(
        lambda: defaultdict(list))
    per_kind: dict[str, dict[str, int]] = defaultdict(lambda: {
        "expected": 0,
        "actual": 0,
        "matched": 0,
        "excluded_expected": 0,
        "excluded_actual": 0,
        "excluded_matched": 0,
        "outside_universe": 0,
    })
    for leaf, h in zip(relifted, actual_leaf_hashes):
        kind = _op_name_of(leaf)
        relift_pool[kind][h] += 1
        relift_leaves[kind][h].append(leaf)
        per_kind[kind]["actual"] += 1
        if _expected_discrepancy_reason(leaf) is not None:
            per_kind[kind]["excluded_actual"] += 1
    for by_hash in relift_leaves.values():
        for bucket in by_hash.values():
            bucket.sort(key=lambda leaf: str(leaf.get("source_element_id", "")))

    discrepancies: list[dict[str, Any]] = []
    consumed: dict[str, Counter[str]] = defaultdict(Counter)
    outside = set(outside_universe)
    for index, (leaf, h) in enumerate(zip(expected, expected_leaf_hashes)):
        kind = _op_name_of(leaf)
        if index in outside:
            # Ожидание вне вселенной: ни в знаменателе, ни в недостаче.
            per_kind[kind]["outside_universe"] += 1
            continue
        reason = _expected_discrepancy_reason(leaf)
        per_kind[kind]["expected"] += 1
        if reason is not None:
            per_kind[kind]["excluded_expected"] += 1
        available = relift_pool[kind][h] - consumed[kind][h]
        if available > 0:
            consumed[kind][h] += 1
            per_kind[kind]["matched"] += 1
            if reason is not None:
                per_kind[kind]["excluded_matched"] += 1
        else:
            discrepancies.append({
                "op_name": kind,
                "source_element_id": leaf["source_element_id"],
                "canon_hash": h,
                "reason": (reason
                           or "re-lifted leaf not found for this translated original"),
                "expected_discrepancy_class": reason is not None,
            })

    # F7: every unconsumed actual occurrence is an explicit false-positive.
    for kind in sorted(relift_leaves):
        for h in sorted(relift_leaves[kind]):
            used = consumed[kind][h]
            for leaf in relift_leaves[kind][h][used:]:
                reason = _expected_discrepancy_reason(leaf)
                discrepancies.append({
                    "op_name": kind,
                    "source_element_id": leaf["source_element_id"],
                    "canon_hash": h,
                    "reason": "extra_rebuilt",
                    "expected_discrepancy_class": reason is not None,
                })

    comparisons = [
        KindComparison(
            op_name=kind,
            expected=counts["expected"],
            actual=counts["actual"],
            matched=counts["matched"],
            excluded_expected=counts["excluded_expected"],
            excluded_actual=counts["excluded_actual"],
            excluded_matched=counts["excluded_matched"],
            outside_universe=counts["outside_universe"],
        )
        for kind, counts in sorted(per_kind.items())
    ]
    discrepancies.sort(key=lambda d: (d["op_name"], d["source_element_id"]))
    return match, expected_hash, actual_hash, comparisons, discrepancies


def _percentages(
    comparisons: Sequence[KindComparison],
) -> MetricTotals:
    """Return symmetric raw/adjusted precision+recall totals.

    A zero denominator is N/A (``None``), never a vacuous 100%.  ``adjusted``
    excludes only leaf-specific expected discrepancy evidence.
    """

    total_expected = sum(c.expected for c in comparisons)
    total_actual = sum(c.actual for c in comparisons)
    total_matched = sum(c.matched for c in comparisons)
    adjusted_expected = sum(
        c.expected - c.excluded_expected for c in comparisons)
    adjusted_actual = sum(c.actual - c.excluded_actual for c in comparisons)
    adjusted_matched = sum(
        c.matched - c.excluded_matched for c in comparisons)
    return MetricTotals(
        total_expected=total_expected,
        total_actual=total_actual,
        total_matched=total_matched,
        total_extra=total_actual - total_matched,
        adjusted_expected=adjusted_expected,
        adjusted_actual=adjusted_actual,
        adjusted_matched=adjusted_matched,
        raw_precision_pct=_ratio_pct(total_matched, total_actual),
        raw_recall_pct=_ratio_pct(total_matched, total_expected),
        adjusted_precision_pct=_ratio_pct(adjusted_matched, adjusted_actual),
        adjusted_recall_pct=_ratio_pct(adjusted_matched, adjusted_expected),
    )


# ── created-id collection from witness read-backs ────────────────────────────


def collect_created_ids(rebuild_results: Sequence[Mapping[str, Any]]) -> list[str]:
    """Gather the ElementIds the rebuild created, from witness read-backs.

    Each per-op program result is the serving ``handle_revit_rebuild`` envelope
    ``{"ok": True, "result": {<op_id>: {"id": "<elementid>", ...}, ...}}``.  The
    per-op ``id`` is the post-commit witness read-back (authoring ``__results``),
    the truth record independent of the create call's echo.  A result missing its
    ``id`` is skipped here but surfaces later as a re-extract shortfall — never a
    silent success.  Ids are returned sorted+deduped (I4).
    """

    ids: set[str] = set()
    for envelope in rebuild_results:
        if not isinstance(envelope, Mapping):
            continue
        payload = envelope.get("result", envelope)
        if not isinstance(payload, Mapping):
            continue
        for value in payload.values():
            if isinstance(value, Mapping):
                # `id` — ИДЕНТИЧНОСТЬ элемента опа (закон переписи), а не
                # свидетельство рождения. Оп, который ИЗМЕНИЛ существующий
                # элемент, говорит это явно (`created: false`), и его id
                # сюда не идёт: A5 удаляет по этому списку, и чужой элемент
                # в нём означал бы удаление чужого.
                #
                # ЗАМЕР 28.07 (пересборка №5): у ячейки витража исход бывает
                # обоим — тип стены рождает НОВЫЙ элемент, тип панели
                # меняется на месте. Ключ отсутствует у всех прочих опов,
                # и для них поведение прежнее.
                if value.get("created") is False:
                    continue
                created = value.get("id") or value.get("element_id")
                if isinstance(created, str) and created.strip():
                    ids.add(created.strip())
                elif isinstance(created, int):
                    ids.add(str(created))
    return sorted(ids, key=lambda v: (int(v) if v.isdigit() else 0, v))


def collect_created_by_op(envelope: Mapping[str, Any]) -> dict[str, str]:
    """Bind compiler op ids to post-commit ElementIds from witness readbacks.

    Tier-G acceptance cannot use an unordered ``created_ids`` bag: it must
    prove that the element re-read after commit is the result of the exact
    escrow op whose expectation was pre-registered.  Duplicate element ids or
    two different ids for one op are contradictions and fail closed.
    """

    if not isinstance(envelope, Mapping):
        return {}
    payload = envelope.get("result", envelope)
    if not isinstance(payload, Mapping):
        return {}
    result: dict[str, str] = {}
    owners: dict[str, str] = {}
    for raw_op_id, value in payload.items():
        if not isinstance(raw_op_id, str) or not raw_op_id:
            continue
        if not isinstance(value, Mapping) or value.get("created") is False:
            continue
        raw_created = value.get("id") or value.get("element_id")
        if isinstance(raw_created, bool) or not isinstance(
                raw_created, (str, int)):
            continue
        created = str(raw_created).strip()
        if not created:
            continue
        previous = result.get(raw_op_id)
        if previous is not None and previous != created:
            raise IdempotenceError(
                "created_identity_conflict",
                "один op witness заявил два разных ElementId",
                raw_op_id,
            )
        owner = owners.get(created)
        if owner is not None and owner != raw_op_id:
            raise IdempotenceError(
                "created_identity_conflict",
                "два op witness заявили один созданный ElementId",
                created,
            )
        result[raw_op_id] = created
        owners[created] = raw_op_id
    return result


# ── executor / runner protocols (injected; mocked in tests) ──────────────────

# ``rebuild_program(program) -> serving-style envelope`` — one materialized
# per-op program executed live (mirrors serving.handle_revit_rebuild's live arm).
RebuildRunner = Callable[[dict], Awaitable[Mapping[str, Any]]]
# ``read_only(cs) -> raw bridge result`` — the re-extract read-back transport.
ReadExecutor = Callable[[str], Awaitable[Any]]
# ``delete_program(program) -> envelope`` — a chunked destructive delete.
DeleteRunner = Callable[[dict], Awaitable[Mapping[str, Any]]]
# ``sweep_current_run() -> envelope`` — exact run-owned reconciliation.
SweepRunner = Callable[[], Awaitable[Mapping[str, Any]]]


class RecoveryHooks(Protocol):
    """Durable lifecycle seam; implemented by the serving recovery adapter."""

    @property
    def resume_created_ids(self) -> Sequence[str]: ...

    async def prepare_rebuild_plan(
        self,
        program_ids: Sequence[str],
    ) -> Mapping[str, Sequence[str]]: ...

    async def after_rebuilt(self, created_ids: Sequence[str]) -> None: ...

    async def after_compared(self, report: Mapping[str, Any]) -> None: ...

    async def before_cleanup(
        self, created_ids: Sequence[str], *, retain: bool,
    ) -> None: ...

    async def after_cleanup(
        self,
        created_ids: Sequence[str],
        *,
        retain: bool,
        cleanup_ok: bool,
        cleanup_detail: str,
    ) -> None: ...


def build_rebuild_plan(
    programs: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Bind deterministic program ids to one exact, ordered rebuild plan.

    The program id covers the full plan digest, ordinal, and exact canonical
    program payload.  Thus identical chunks at different positions remain
    distinct, while any changed/reordered/added chunk invalidates every id.
    ``program_id`` is internal metadata accepted only by the compiler's bulk
    path and does not change generated C#.
    """

    canonical_programs: list[bytes] = []
    copied: list[dict[str, Any]] = []
    for index, program in enumerate(programs):
        if not isinstance(program, Mapping):
            raise IdempotenceError(
                "invalid_rebuild_plan",
                "материализованный rebuild-план содержит не-объект",
                f"program[{index}]={type(program).__name__}",
            )
        row = dict(program)
        if "program_id" in row:
            raise IdempotenceError(
                "invalid_rebuild_plan",
                "материализованный rebuild-план уже содержит program_id",
                f"program[{index}]",
            )
        try:
            encoded = json.dumps(
                row,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise IdempotenceError(
                "invalid_rebuild_plan",
                "rebuild-план не канонизируется",
                f"program[{index}]: {exc}",
            ) from exc
        copied.append(row)
        canonical_programs.append(encoded)

    plan_hasher = hashlib.sha256()
    version_bytes = REBUILD_PLAN_VERSION.encode("ascii")
    plan_hasher.update(len(version_bytes).to_bytes(8, "big"))
    plan_hasher.update(version_bytes)
    for encoded in canonical_programs:
        digest = hashlib.sha256(encoded).digest()
        plan_hasher.update(len(encoded).to_bytes(8, "big"))
        plan_hasher.update(digest)
    plan_digest = plan_hasher.digest()

    result: list[dict[str, Any]] = []
    for index, (row, encoded) in enumerate(zip(copied, canonical_programs)):
        program_hasher = hashlib.sha256()
        program_hasher.update(REBUILD_PLAN_VERSION.encode("ascii"))
        program_hasher.update(plan_digest)
        program_hasher.update(index.to_bytes(8, "big"))
        program_hasher.update(hashlib.sha256(encoded).digest())
        result.append({**row, "program_id": program_hasher.hexdigest()})
    return tuple(result)


def _resume_created_ids(
    confirmed: Mapping[str, Sequence[str]],
    planned_ids: Sequence[str],
) -> list[str]:
    """Validate recovery output and return a stable, duplicate-free id list."""

    planned = set(planned_ids)
    if any(key not in planned for key in confirmed):
        raise IdempotenceError(
            "recovery_plan_mismatch",
            "журнал содержит receipt от другого rebuild-плана",
        )
    created: set[str] = set()
    for program_id in planned_ids:
        if program_id not in confirmed:
            continue
        values = confirmed[program_id]
        if (not isinstance(values, Sequence)
                or isinstance(values, (str, bytes, bytearray))):
            raise IdempotenceError(
                "recovery_receipt_invalid",
                "receipt подтверждённого чанка не содержит список id",
                program_id,
            )
        for value in values:
            if not isinstance(value, str) or not value:
                raise IdempotenceError(
                    "recovery_receipt_invalid",
                    "receipt подтверждённого чанка содержит невалидный id",
                    program_id,
                )
            if value in created:
                raise IdempotenceError(
                    "recovery_receipt_invalid",
                    "два подтверждённых чанка заявляют один ElementId",
                    value,
                )
            created.add(value)
    return sorted(created, key=lambda value: (
        int(value) if value.isdigit() else 0, value))


def _delete_program(ids: Sequence[str]) -> dict:
    """A destructive delete program for one id chunk (allow_destructive=true)."""

    return {
        "ir_version": spec.IR_VERSION,
        "intent": "A5 idempotence cleanup — удалить Δ-элементы",
        "allow_destructive": True,
        "ops": [
            {"op": "delete", "id": f"del_{i}",
             "target": {"by": "element_id", "value": int(eid)}}
            for i, eid in enumerate(ids)
            if str(eid).isdigit()
        ],
    }


def _stamp_census(envelope: Any) -> Optional[dict[str, Any]]:
    """Перепись штампа из ответа зачистки, если она полна и читаема.

    Перепись — АВТОРИТЕТНЕЕ поштучных витнесов удаления, потому что отвечает
    на настоящий вопрос уборки: «не осталось ли в модели ЧЕГО-НИБУДЬ нашего».
    Поштучный проход отвечает на более узкий: «подтвердил ли Revit удаление
    каждого id», — и на каскаде он ложно-отрицателен.

    ЗАМЕР 28.07 (прогон №4): из 1236 созданных 12 элементов исчезли ВМЕСТЕ СО
    СВОИМИ ХОЗЯЕВАМИ (ячейки витража уходят с носителем), их удаление
    вернулось отказом «элемент не найден» — и уборка объявила себя
    неуспешной, отбросив вдобавок весь чанк: 1108/1236 вместо 1224/1236. При
    этом финальная перепись штампа того же прогона: found 0, remaining 0,
    witnesses_complete true — в модели не осталось ничего.
    """

    if not isinstance(envelope, Mapping) or envelope.get("ok") is not True:
        return None
    payload = envelope.get("result")
    if not isinstance(payload, Mapping):
        return None
    if payload.get("witnesses_complete") is not True:
        return None
    remaining = payload.get("remaining")
    if isinstance(remaining, bool) or not isinstance(remaining, int):
        return None
    remaining_ids = payload.get("remaining_ids")
    if not isinstance(remaining_ids, list) or len(remaining_ids) != remaining:
        return None
    return {"remaining": remaining, "remaining_ids": list(remaining_ids)}


async def cleanup_created(
    created_ids: Sequence[str],
    delete_runner: DeleteRunner,
) -> tuple[bool, str]:
    """Delete every created id in bounded chunks.  Returns ``(ok, detail)``.

    Called from ``finally``; a failure leaves orphaned Δ-elements, so its outcome
    is reported, never swallowed.  Every chunk is attempted even if an earlier one
    fails, so a transient chunk error does not abandon the rest.
    """

    if not created_ids:
        return True, "nothing to clean up"
    chunks = [
        list(created_ids[i:i + _DELETE_CHUNK])
        for i in range(0, len(created_ids), _DELETE_CHUNK)
    ]
    failures: list[str] = []
    deleted = 0
    for index, chunk in enumerate(chunks):
        try:
            envelope = await delete_runner(_delete_program(chunk))
        except Exception as exc:  # noqa: BLE001 — a runner death is a cleanup miss
            failures.append(f"chunk {index}: {exc!r}")
            continue
        confirmed = _deleted_id_witnesses(envelope)
        expected = {str(value) for value in chunk}
        missing = sorted(expected - confirmed)
        unexpected = sorted(confirmed - expected)
        if (isinstance(envelope, Mapping) and envelope.get("ok") is True
                and not missing and not unexpected):
            deleted += len(chunk)
        else:
            failures.append(
                f"chunk {index}: missing={missing[:8]!r}, "
                f"unexpected={unexpected[:8]!r}; {_short(envelope)}")
    if failures:
        return False, (
            f"deleted {deleted}/{len(created_ids)}; "
            f"failed: {'; '.join(failures[:8])}")
    return True, f"deleted {deleted}/{len(created_ids)} Δ-elements"


def _deleted_id_witnesses(value: Any) -> set[str]:
    """Collect only explicit ``deleted_id`` witnesses from a runner envelope."""

    found: set[str] = set()
    if isinstance(value, Mapping):
        deleted_id = value.get("deleted_id")
        if isinstance(deleted_id, (str, int)) and not isinstance(deleted_id, bool):
            found.add(str(deleted_id))
        for nested in value.values():
            found.update(_deleted_id_witnesses(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.update(_deleted_id_witnesses(nested))
    return found


def curtain_hosts_needing_isolation(curtain_index: Any) -> frozenset[str]:
    """Витражные носители, чью группу нельзя пускать в общий чанк.

    ПОВОД ЗАМЕРЕН, а не выведен. Живая пересборка фасада SOB6.2 (28.07,
    прогон v7) откатила чанк из 250 опов целиком:

        Не удалось сформировать тип "ATR_Панель витража с решеткой :
        Интегрированная Вентиляционная решетка". [элементы: 11401364, 11402544]

    Оба названных элемента — АВТО-ПАНЕЛИ, которые Revit порождает сам при
    создании стены витражного типа: у такого типа параметр «Curtain Panel»
    (AUTO_PANEL_WALL) указывает на ЗАГРУЖАЕМОЕ СЕМЕЙСТВО, и Revit
    инстанцирует его в каждой ячейке. Одна такая стена, поставленная пробой
    в одиночку (П1), строится; несколько в одной транзакции — нет.

    Удержать это per-op изоляцией нельзя ПО ПОСТРОЕНИЮ: по документации
    сборок ``SubTransaction.Commit`` — «the changes are not permanently
    committed … only when the active transaction is committed», а отказ
    регенерации приходит отложенно, на Commit родителя. Значит единственный
    контур — РАЗМЕР ЧАНКА.

    ПРИЗНАК СТРУКТУРНЫЙ, без единого имени (INVARIANT #1): тип разрезки
    носителя прочитан (``default_panel_state == "ok"``) И он инстанцируется
    в ячейке ЭКЗЕМПЛЯРОМ СЕМЕЙСТВА без стены-тела. Когда «Curtain Panel»
    указывает на тип СТЕНЫ, ячейку занимает стена (у панели есть
    ``host_panel_id``), и произвольного кода семейства в порождении нет.

    ЗАМЕР ПРИЗНАКА (v6/v7 фасада): выбирает 8 и 9 носителей из 1201/1203 —
    ровно решёточные, ни одного ложного. Девятый на v7 — стена, оставленная
    в модели пробой П1.
    """

    records: Any = getattr(curtain_index, "records", None)
    rows: list[tuple[str, Any]]
    if records is not None:
        rows = [(record.wall_id, record) for record in records]
    elif isinstance(curtain_index, Mapping):
        raw = curtain_index.get("curtain_index", curtain_index)
        if not isinstance(raw, Mapping):
            return frozenset()
        rows = [(host_id, row) for host_id, row in raw.items()
                if isinstance(host_id, str)]
    else:
        return frozenset()

    def _field(row: Any, name: str) -> Any:
        if isinstance(row, Mapping):
            return row.get(name)
        value = getattr(row, name, None)
        return getattr(value, "value", value)

    isolate: set[str] = set()
    for host_id, row in rows:
        if not _field(row, "curtain_available"):
            continue
        if _field(row, "default_panel_state") != "ok":
            continue
        default_type = _field(row, "default_panel_type_id")
        if not default_type:
            continue
        for panel in _field(row, "panels") or ():
            if _field(panel, "type_id") != default_type:
                continue
            if (_field(panel, "is_family_instance")
                    and not _field(panel, "host_panel_id")):
                isolate.add(host_id)
                break
    return frozenset(isolate)


def _isolation_from_artifacts(
    debug_dir: Optional[str],
    explicit: Optional[Iterable[str]],
) -> frozenset[str]:
    """Кого изолировать: переданное вызывающим, иначе — из разбора рядом.

    Индекса нет — изоляции нет: это ровно прежнее поведение, и оно ВИДНО в
    отчёте (``isolated_groups``), а не подразумевается.
    """

    if explicit is not None:
        return frozenset(explicit)
    if not debug_dir:
        return frozenset()
    path = pathlib.Path(debug_dir) / "curtain.index.json"
    if not path.is_file():
        return frozenset()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    return curtain_hosts_needing_isolation(payload)


def _isolated_programs(
    materialized: Sequence[Mapping[str, Any]],
    planned: Sequence[Mapping[str, Any]],
    isolate: frozenset[str],
) -> dict[str, dict[str, Any]]:
    """``program_id`` изолированных программ -> заготовка квитанции.

    Изолированная программа опознаётся по составу, а не по порядковому
    номеру: в ней есть оп ИЗОЛИРОВАННОГО носителя. Обратное невозможно по
    построению материализатора — такие группы вынуты из общей упаковки, — и
    именно поэтому радиус отказа здесь равен одной группе.
    """

    if not isolate:
        return {}
    anchors = {_op_id(source_id) for source_id in isolate}
    receipts: dict[str, dict[str, Any]] = {}
    for program, plan in zip(materialized, planned):
        ops = program.get("ops") or ()
        op_ids = [str(op.get("id")) for op in ops if isinstance(op, Mapping)]
        hit = sorted(set(op_ids) & anchors)
        if not hit:
            continue
        receipts[str(plan["program_id"])] = {
            "program_id": str(plan["program_id"]),
            "source_ids": [op_id[1:] for op_id in hit],
            "op_ids": op_ids,
            "ops": len(op_ids),
        }
    return receipts


def refusal_shares(
    chunk_failures: Sequence[Mapping[str, Any]],
    planned_programs: Sequence[Mapping[str, Any]],
) -> tuple[float, float, bool]:
    """``(доля чанков, доля опов, превышен ли порог)``.

    Оба измерения обязательны, потому что одно из них всегда врёт: solo-чанк
    несёт ОДИН оп, большой — до 250. Семь отказавших solo из 28 программ это
    25% чанков и 0.26% плана (валить прогон было бы враньём в одну сторону);
    три отказавших больших чанка — 10.7% чанков и 27.5% плана (пропустить их
    было бы враньём в другую). Порог берёт максимум из двух.
    """

    refused_chunks = len(chunk_failures)
    refused_ops = sum(int(row.get("ops") or 0) for row in chunk_failures)
    planned_ops = sum(
        len(program.get("ops") or ()) for program in planned_programs)
    chunk_share = refused_chunks / max(len(planned_programs), 1)
    op_share = refused_ops / max(planned_ops, 1)
    exceeded = (chunk_share > MAX_REFUSED_CHUNK_SHARE
                or op_share > MAX_REFUSED_CHUNK_SHARE)
    return chunk_share, op_share, exceeded


def _refused_without_commit(envelope: Any) -> bool:
    """ИЗВЕСТНЫЙ отрицательный исход чанка — читается по полю, не по тексту.

    Поле ставит ровно та ветка ``serving``, которая пишет в журнал квитанцию
    ``refused_without_commit`` (Revit ответил, транзакция откатена, ни одного
    созданного id). Один источник истины, два читателя: журнал и оркестратор.

    Разбирать вместо этого ``bridge_detail`` по подстроке было бы нельзя:
    ``timeout_unconfirmed`` тоже приходит с ``ok=false``, но там ответа НЕТ и
    Revit мог зафиксировать — такой чанк обязан валить прогон, иначе fail-soft
    молча построит остаток поверх неизвестного состояния документа.
    """

    return (isinstance(envelope, Mapping)
            and envelope.get("outcome") == "refused_without_commit")


def _bridge_detail(envelope: Any) -> str:
    """Ответ моста ДОСЛОВНО.

    Урезание — отдельный класс потерь: 28.07 сообщение об отказе резалось
    дважды (300 и 160 символов) и уносило с собой id виновных элементов,
    из-за чего живой прогон приходилось повторять ради одной строки.
    Здесь текст не режется вовсе: квитанция существует ровно затем, чтобы
    следующий читатель не гонял Revit заново.
    """

    if isinstance(envelope, Mapping):
        # ПОРЯДОК ЗНАЧИМ: у конверта serving поле `error` держит КОД
        # («rebuild_exec»), а текст Revit лежит в `bridge_detail`. Спросив
        # `error` первым, квитанция несла бы код вместо улики.
        for key in ("bridge_detail", "message", "detail", "error"):
            value = envelope.get(key)
            if isinstance(value, str) and value:
                return value
    return repr(envelope)


def _short(value: Any) -> str:
    return repr(value)[:4000]


# ── the orchestrator ─────────────────────────────────────────────────────────


async def run_idempotence(
    leaves: Sequence[L1Node],
    metadata: L0Document,
    *,
    doc_stamp: str,
    safety: SafetyContext,
    rebuild_runner: Optional[RebuildRunner] = None,
    read_executor: Optional[ReadExecutor] = None,
    delete_runner: Optional[DeleteRunner] = None,
    sweep_runner: Optional[SweepRunner] = None,
    delta_mm: Vec3 = DELTA_MM,
    dry_run: bool = True,
    debug_dir: Optional[str] = None,
    keep_delta: bool = False,
    recovery: Optional[RecoveryHooks] = None,
    ground_snapshot: Optional[dict] = None,
    isolate_source_ids: Optional[Iterable[str]] = None,
    atom_escrow: bool = False,
    geometry: GeometryExtraction | None = None,
    escrow_source_ids: Optional[Iterable[str]] = None,
) -> IdempotenceReport:
    """Measure decompile→rebuild idempotence for one already-decompiled model.

    ``leaves`` are the decompiled L1 leaves (e.g. ``iter_l1_leaves(tree)``);
    ``metadata`` is the decompile's L0Document (levels/grids/rooms) used to build
    the re-extracted document's datum context.  With ``dry_run=True`` (default)
    the materialized Δ-programs are compile-gated but NOT executed, no ids are
    created, and no cleanup runs — the safe offline verdict.  The LIVE path
    (``dry_run=False``) is fail-closed: it refuses unless ``safety`` proves the
    gate AND a copy title.  Every failure is a typed :class:`IdempotenceReport`
    with ``error`` set — this function never raises.
    """

    if not isinstance(atom_escrow, bool):
        return _errored(
            doc_stamp, delta_mm, "", 0, 0,
            IdempotenceError(
                "atom_escrow_invalid",
                "atom_escrow должен быть boolean"),
            dry_run=dry_run)
    if atom_escrow and not isinstance(geometry, GeometryExtraction):
        return _errored(
            doc_stamp, delta_mm, "", 0, 0,
            IdempotenceError(
                "atom_escrow_missing",
                "Tier-G A5 требует typed GeometryExtraction"),
            dry_run=dry_run)
    if not atom_escrow and geometry is not None:
        return _errored(
            doc_stamp, delta_mm, "", 0, 0,
            IdempotenceError(
                "atom_escrow_invalid",
                "geometry требует явный atom_escrow=true"),
            dry_run=dry_run)
    if not atom_escrow and escrow_source_ids is not None:
        return _errored(
            doc_stamp, delta_mm, "", 0, 0,
            IdempotenceError(
                "atom_escrow_invalid",
                "escrow_source_ids требует явный atom_escrow=true"),
            dry_run=dry_run)

    op_leaves = _op_leaves(leaves)
    datums_skipped = _datum_count(leaves)
    atoms_total = _atom_count(leaves)
    atoms_excluded = atoms_total
    atoms_escrowed = 0
    non_datum_total = len(op_leaves) + atoms_total
    expected_leaves = _translate_originals(op_leaves, delta_mm)
    expected_hash = FidelityCanon.multiset_hash(expected_leaves, _ORIGIN)

    # Materialize op-leaves at Δ (datums excluded, host-atomic, tail rooms).  A
    # materialize failure is a typed refusal, not a crash.
    isolate = _isolation_from_artifacts(debug_dir, isolate_source_ids)
    try:
        materialized = leaves_to_program(
            leaves,
            mode="escrow" if atom_escrow else "same_document",
            geometry=geometry if atom_escrow else None,
            escrow_source_ids=(escrow_source_ids if atom_escrow else None),
            offset_mm=delta_mm,
            solo_source_ids=isolate)
        # Real materializers prove every raw chunk at the typed mid-end
        # boundary before the idempotence layer adds its global ``program_id``.
        # Older test doubles intentionally expose only ``programs``; they keep
        # their legacy seam, while a real typed refusal is never ignored.
        if (hasattr(materialized, "compiler_ready")
                and not materialized.compiler_ready):
            refused = [
                check.as_dict() for check in materialized.plan_checks
                if not check.accepted
            ]
            raise IdempotenceError(
                "materialize_plan_refused",
                "материализованные чанки не прошли typed KIR plan",
                json.dumps(refused[:8], ensure_ascii=False, sort_keys=True),
            )
        planned_programs = build_rebuild_plan(materialized.programs)
        escrow_records = tuple(
            getattr(materialized, "escrowed", ()) or ())
        materialize_stats = getattr(materialized, "stats", None)
        atoms_escrowed = int(
            getattr(materialize_stats, "atoms_escrowed", 0) or 0)
        atoms_excluded = int(
            getattr(materialize_stats, "atoms_skipped", atoms_total)
            if materialize_stats is not None else atoms_total)
        if atoms_excluded + atoms_escrowed != atoms_total:
            raise IdempotenceError(
                "atom_accounting_mismatch",
                "materializer не отчитался по каждому atom leaf",
                f"total={atoms_total} skipped={atoms_excluded} "
                f"escrowed={atoms_escrowed}",
            )
        escrow_by_program = {
            str(planned_programs[record.program_index]["program_id"]): record
            for record in escrow_records
        }
        if len(escrow_by_program) != len(escrow_records):
            raise IdempotenceError(
                "atom_escrow_plan_mismatch",
                "два atom escrow expectation попали в одну program identity",
            )
        isolated_by_program = _isolated_programs(
            materialized.programs, planned_programs, isolate)
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, IdempotenceError):
            error = exc
        else:
            error = IdempotenceError(
                "materialize_failed",
                "материализация Δ-программы не удалась",
                repr(exc),
            )
        return _errored(
            doc_stamp, delta_mm, expected_hash, len(op_leaves), datums_skipped,
            error,
            dry_run=dry_run, atoms_excluded=atoms_excluded,
            atoms_escrowed=atoms_escrowed)

    # ── dry run: compile-gate every chunk, no execution, empty comparison ────
    if dry_run:
        from kukai.ir.compiler import compile_rebuild_chunk
        refused: list[str] = []
        for index, program in enumerate(planned_programs):
            # Single rebuild policy point — the dry run must compile EXACTLY
            # what the live runners will execute (bulk+per_op+de-join).
            # Каталог источника обязателен: без него заземление не резолвит
            # селекторы по имени и отказ КИР-G103 говорит о слепоте гейта, а
            # не о программе (serving.source_catalogue_snapshot).
            out = compile_rebuild_chunk(
                program, revit_version=metadata.revit_version,
                snapshot=ground_snapshot)
            if not out.ok:
                refused.append(
                    f"chunk {index}: "
                    + ", ".join(d.code for d in out.diagnostics[:3]))
        error = None
        if refused:
            error = IdempotenceError(
                "dry_run_refused",
                "материализованные Δ-чанки отклонены компилятором",
                "; ".join(refused[:8])).to_dict()
        return IdempotenceReport(
            doc_stamp=doc_stamp,
            delta_mm=delta_mm,
            multiset_match=None,
            expected_hash=expected_hash,
            actual_hash="",
            total_expected=len(op_leaves),
            total_matched=0,
            raw_exact_pct=None,
            adjusted_exact_pct=None,
            per_kind=(),
            discrepancies=(),
            datums_skipped=datums_skipped,
            atoms_excluded=atoms_excluded,
            atoms_escrowed=atoms_escrowed,
            form_expectations=tuple(
                record.as_dict() for record in escrow_records),
            non_datum_total=non_datum_total,
            comparable_coverage_pct=None,
            created_ids=(),
            cleanup_ok=True,
            cleanup_detail="dry_run: no elements created",
            dry_run=True,
            error=error,
        )

    # ── live path: fail-closed safety guard FIRST ────────────────────────────
    refusal = safety.refusal()
    if refusal is not None:
        return _errored(
            doc_stamp, delta_mm, expected_hash, len(op_leaves), datums_skipped,
            refusal, dry_run=False, atoms_excluded=atoms_excluded,
            atoms_escrowed=atoms_escrowed,
            form_expectations=tuple(
                record.as_dict() for record in escrow_records))
    if (rebuild_runner is None or read_executor is None
            or delete_runner is None or sweep_runner is None):
        return _errored(
            doc_stamp, delta_mm, expected_hash, len(op_leaves), datums_skipped,
            IdempotenceError("no_runners",
                             "живой путь требует rebuild/read/delete/sweep раннеры"),
            dry_run=False, atoms_excluded=atoms_excluded,
            atoms_escrowed=atoms_escrowed,
            form_expectations=tuple(
                record.as_dict() for record in escrow_records))

    created_ids: list[str] = []
    escrow_created_by_op: dict[str, str] = {}
    form_verdict_rows: tuple[dict[str, Any], ...] = ()
    form_accepted = 0
    form_rejected = 0
    form_inconclusive = 0
    form_read_error = ""
    body: Optional[dict[str, Any]] = None   # verdict fields, pre-cleanup
    pending_error: Optional[IdempotenceError] = None
    recovery_cleanup_started = False
    cleanup_ok = True
    cleanup_detail = "not reached"
    # Накопители отказов живут ВНЕ try: ошибка на поздней фазе (re-extract,
    # сравнение, уборка) не должна стирать уже засвидетельствованные отказы —
    # иначе отчёт о падении молчит о том, что часть плана Revit отверг, и
    # следующий читатель гоняет живой Revit ради строки, которая у нас была.
    isolated_failures: list[dict[str, Any]] = []
    chunk_failures: list[dict[str, Any]] = []
    op_refusals: list[dict[str, Any]] = []
    try:
        confirmed_programs: Mapping[str, Sequence[str]] = {}
        planned_ids = tuple(
            str(program["program_id"]) for program in planned_programs)
        if recovery is not None:
            confirmed_programs = await recovery.prepare_rebuild_plan(
                planned_ids)
            created_ids = _resume_created_ids(
                confirmed_programs, planned_ids)
            for program_id, record in escrow_by_program.items():
                if program_id not in confirmed_programs:
                    continue
                raw_values = confirmed_programs[program_id]
                if (not isinstance(raw_values, Sequence)
                        or isinstance(raw_values, (str, bytes, bytearray))):
                    raise IdempotenceError(
                        "atom_escrow_receipt_invalid",
                        "escrow program receipt не содержит список ElementId",
                        program_id,
                    )
                values = tuple(raw_values)
                if len(values) > 1:
                    raise IdempotenceError(
                        "atom_escrow_receipt_invalid",
                        "escrow program receipt содержит больше одного ElementId",
                        f"{program_id}: {values!r}",
                    )
                # Empty is a durable refused_without_commit receipt.  It keeps
                # the form verdict inconclusive and the atom in denominator.
                if values:
                    escrow_created_by_op[record.op_id] = values[0]

        # Rebuild each materialized per-op program; collect created ids as we go
        # so a mid-run failure still cleans up whatever was created.
        created_set = set(created_ids)
        for index, program in enumerate(planned_programs):
            program_id = str(program["program_id"])
            if program_id in confirmed_programs:
                continue
            escrow_record = escrow_by_program.get(program_id)
            envelope = await rebuild_runner(program)
            if isinstance(envelope, Mapping):
                # Отказы собираются ДО проверки ok: чанк мог закоммититься с
                # отказавшими опами внутри, и это ровно тот случай, ради
                # которого поле заведено.
                for row in (envelope.get("op_refusals") or ()):
                    if isinstance(row, Mapping):
                        op_refusals.append({
                            **row,
                            "kind": "op_refused_in_commit",
                            "program_id": program_id,
                        })
                # ОП БЕЗ ИСХОДА — НЕИЗВЕСТНОСТЬ, а не отказ. Дисциплина та
                # же, что у timeout_unconfirmed: чанк закоммичен, но что
                # стало с неучтёнными опами, никто не знает, и строить
                # остаток поверх этого нельзя. Чанковый fail-soft сюда НЕ
                # применяется намеренно — у конверта нет `outcome`, поэтому
                # ниже сработает фатальный путь.
                if envelope.get("error") == "ops_unaccounted":
                    raise IdempotenceError(
                        "ops_unaccounted",
                        "чанк не отчитался по всем опам — есть опы без исхода",
                        _bridge_detail(envelope))
            for element_id in collect_created_ids([
                    envelope if isinstance(envelope, Mapping) else {}]):
                created_set.add(element_id)
            if isinstance(envelope, Mapping):
                by_op = collect_created_by_op(envelope)
                if escrow_record is not None:
                    created = by_op.get(escrow_record.op_id)
                    if created is not None:
                        prior = escrow_created_by_op.get(escrow_record.op_id)
                        if prior is not None and prior != created:
                            raise IdempotenceError(
                                "created_identity_conflict",
                                "escrow op изменил подтверждённый ElementId",
                                escrow_record.op_id,
                            )
                        escrow_created_by_op[escrow_record.op_id] = created
            created_ids = sorted(created_set, key=lambda value: (
                int(value) if value.isdigit() else 0, value))
            if not (isinstance(envelope, Mapping)
                    and envelope.get("ok") is True):
                # An escrow program contains exactly one dependency-free atom.
                # A witnessed rollback therefore has a proven one-atom radius:
                # no semantic chunk was lost.  Keep the atom in the denominator
                # and let its independent form verdict close as inconclusive.
                if (escrow_record is not None
                        and _refused_without_commit(envelope)):
                    continue
                # КАРВАУТ РОВНО ПО ДОКАЗАННОМУ РАДИУСУ. Изолированная
                # программа — это ОДНА хост-группа (так её и построил
                # материализатор), поэтому её отказ не может утащить
                # соседей: их в ней нет. Отказ ОБЫЧНОГО чанка по-прежнему
                # фатален — там радиус равен всей программе, и «поедем
                # дальше» означало бы молча потерять до 250 опов.
                #
                # ПОВОД ЗАМЕРЕН (прогон №3, 28.07): шесть больших чанков
                # Committed (1226 элементов), solo №1 Committed, solo №2
                # откатился «Не удалось сформировать тип» — и прогон умер,
                # а уборка снесла 1099 уже построенных элементов. Ровно
                # один носитель из 1200 стоил всей пересборки.
                receipt = isolated_by_program.get(program_id)
                if receipt is not None:
                    isolated_failures.append({
                        **receipt,
                        "kind": "isolated_rebuild_refused",
                        "bridge_detail": _bridge_detail(envelope),
                    })
                    continue
                # ЧАНКОВЫЙ FAIL-SOFT (29.07). Разделительная черта — НЕ
                # «чанк или solo», а ИЗВЕСТЕН ЛИ ИСХОД. Revit ответил,
                # транзакция откатена, витнесов нет — программа закрыта, и
                # прогон обязан доехать до цифры. Ответа нет
                # (`timeout_unconfirmed`) — Revit мог зафиксировать, и
                # строить поверх неизвестного состояния нельзя: там по-
                # прежнему фатальный отказ.
                #
                # ПОВОД ЗАМЕРЕН (пересборки №9/№10, 28-29.07): девятый чанк
                # из 28 откатился, прогон умер, уборка снесла 2009 уже
                # построенных элементов, сравнения не было вовсе
                # (comparison_performed=false). Двенадцать живых опытов
                # (Э1-Э12) минимальный репродьюсер не нашли — значит цифра
                # обязана выживать при неизвестной ловушке.
                if _refused_without_commit(envelope):
                    ops = program.get("ops") or ()
                    chunk_failures.append({
                        "kind": "chunk_rebuild_refused",
                        "program_id": program_id,
                        "chunk_index": index,
                        "ops": len(ops),
                        "op_ids": [str(op.get("id")) for op in ops
                                   if isinstance(op, Mapping)],
                        "bridge_detail": _bridge_detail(envelope),
                    })
                    continue
                raise IdempotenceError(
                    "rebuild_failed",
                    "живой rebuild чанка не подтверждён",
                    _short(envelope))

        # ПОРОГ. «Доехать до цифры» не должно превратиться в «построили
        # четверть и назвали это процентом». Порог держится ПО ОБОИМ
        # измерениям: по числу чанков (как договорено) и по доле опов —
        # семь отказавших solo-программ по одному опу это 0.26% плана, а
        # три отказавших больших чанка — 27%, и одно число из двух всегда
        # врёт. Превышение любого — отказ прогона целиком.
        if chunk_failures:
            chunk_share, op_share, exceeded = refusal_shares(
                chunk_failures, planned_programs)
            if exceeded:
                refused_ops = sum(
                    int(row["ops"]) for row in chunk_failures)
                raise IdempotenceError(
                    "too_many_chunks_refused",
                    "отказало слишком много чанков — прогон не даёт честной "
                    "доли модели",
                    f"чанков {len(chunk_failures)}/{len(planned_programs)} "
                    f"({chunk_share:.1%}), опов {refused_ops} "
                    f"({op_share:.1%}), порог "
                    f"{MAX_REFUSED_CHUNK_SHARE:.0%}")

        if not created_ids and not escrow_records:
            raise IdempotenceError(
                "no_created_ids",
                "rebuild не вернул ни одного созданного id (witness-ридбэк пуст)")
        if recovery is not None:
            await recovery.after_rebuilt(created_ids)

        # Tier-G L3 acceptance is a SEPARATE post-commit read.  The emitter's
        # own bbox/triangle witness is necessary but cannot judge itself.  A5
        # re-extracts only the ElementIds bound to escrow op ids by commit
        # receipts, then compares them with the pre-registered plan-bound
        # surface predicates.  Any read defect makes every affected verdict
        # inconclusive; it can never manufacture a match.
        observed_geometry: GeometryExtraction | None = None
        escrow_created_ids = sorted(
            set(escrow_created_by_op.values()),
            key=lambda value: (int(value) if value.isdigit() else 0, value),
        )
        if escrow_created_ids:
            try:
                from kukai.ir.decompile.geom_extract import (
                    build_geometry_extract_cs,
                    extract_geometry,
                    merge_geometry_extractions,
                )
                from kukai.ir.decompile.schema import EXTRACT_BATCH

                geometry_parts = []
                for start in range(0, len(escrow_created_ids), EXTRACT_BATCH):
                    batch = escrow_created_ids[start:start + EXTRACT_BATCH]
                    raw = await read_executor(build_geometry_extract_cs(batch))
                    part = extract_geometry(raw)
                    accounted = {
                        record.element_id for record in part.index
                    } | {
                        failure.element_id for failure in part.failures
                    }
                    if accounted != set(batch):
                        raise IdempotenceError(
                            "form_read_incomplete",
                            "post-commit geometry read не покрывает запрос",
                            f"requested={batch!r} accounted={sorted(accounted)!r}",
                        )
                    geometry_parts.append(part)
                observed_geometry = merge_geometry_extractions(geometry_parts)
            except Exception as exc:  # evidence stays inconclusive, never true
                form_read_error = f"{type(exc).__name__}: {exc}"[:1000]
                observed_geometry = None

        form_verdicts = []
        for record in escrow_records:
            verdict = check_form_acceptance(
                record.expectation,
                observed_geometry,
                created_element_id=escrow_created_by_op.get(record.op_id),
            )
            row = verdict.to_dict()
            row["evidence_digest"] = verdict.evidence_digest
            form_verdicts.append(row)
        form_verdict_rows = tuple(form_verdicts)
        form_accepted = sum(
            row["state"] == FormAcceptanceState.ACCEPTED.value
            for row in form_verdict_rows)
        form_rejected = sum(
            row["state"] == FormAcceptanceState.REJECTED.value
            for row in form_verdict_rows)
        form_inconclusive = sum(
            row["state"] == FormAcceptanceState.INCONCLUSIVE.value
            for row in form_verdict_rows)
        if form_accepted + form_rejected + form_inconclusive != atoms_escrowed:
            raise IdempotenceError(
                "form_acceptance_accounting_mismatch",
                "не каждый escrow expectation получил form verdict",
            )

        # Re-extract ONLY the created ids in bounded pages.  Every page proves
        # exact requested==seen coverage; a disappeared or foreign row is an
        # unknown snapshot, never a smaller plausible comparison set.
        re_elements = []
        try:
            for start in range(0, len(created_ids), REEXTRACT_BATCH):
                batch = created_ids[start:start + REEXTRACT_BATCH]
                raw = await read_executor(build_reextract_cs(batch))
                re_elements.extend(parse_reextract_rows(
                    raw, requested_ids=batch))
        except ReExtractError as exc:
            raise IdempotenceError(
                "reextract_failed", "re-extract Δ-элементов не удался", str(exc))
        # Δ-room boundaries (2026-07-21): the created rooms carry NEW ids, so
        # re-lift needs THEIR re-extracted boundaries — not metadata.rooms
        # (original ids) — or every Δ-room atomizes (live floor-20: 0/87).
        # Fail-open: an unreadable room boundary keeps the original rooms and the
        # room degrades to its prior honest atomization.
        room_ids = [
            element.element_id for element in re_elements
            if element.category == "OST_Rooms"
        ]
        delta_rooms = []
        try:
            for start in range(0, len(room_ids), REEXTRACT_BATCH):
                batch = room_ids[start:start + REEXTRACT_BATCH]
                rraw = await read_executor(build_room_reextract_cs(batch))
                delta_rooms.extend(parse_room_reextract(
                    rraw, requested_ids=batch))
        except Exception:  # noqa: BLE001 — no Δ-room boundary ⇒ rooms atomize
            delta_rooms = None
        re_doc = reextracted_document(metadata, re_elements, rooms=delta_rooms)
        from kukai.ir.decompile.lift import lift_document
        # Side-контекст re-lift'а (live floor evidence 2026-07-21: 12/12
        # пересозданных полов атомизировались — lift_document без индексов не
        # имеет sketch-профилей; та же судьба ждала hosted-двери без
        # family_placement и арки без curve).  Re-lift обязан видеть ТОТ ЖЕ
        # side-контекст, что и оригинальный lift.  Каждый индекс fail-open:
        # его отсутствие деградирует до честной атомизации (как раньше), но
        # не роняет замер.
        def _peel(payload: Any) -> Any:
            if isinstance(payload, Mapping) and isinstance(
                    payload.get("result"), Mapping):
                return payload["result"]
            return payload

        profile_index = None
        try:
            from kukai.ir.decompile.sketch_extract import (
                build_sketch_extract_cs, extract_sketch_profiles)
            sraw = await read_executor(build_sketch_extract_cs())
            profile_index = extract_sketch_profiles(_peel(sraw)).profile_index
        except Exception:  # noqa: BLE001 — no sketch ⇒ floors/roofs atomize
            profile_index = None
        # An attempted-but-missing side index is represented by an empty
        # requested index, not None.  Hosted flips then atomize as unknown
        # instead of silently assuming all-False and producing a false match.
        placement_index = {}
        try:
            from kukai.ir.decompile.family_placement_extract import (
                FamilyPlacementExtraction, build_family_placement_extract_cs)
            fraw = _peel(await read_executor(
                build_family_placement_extract_cs(created_ids)))
            rows = fraw.get("placements") if isinstance(fraw, Mapping) else None
            if isinstance(rows, list):
                placement_index = FamilyPlacementExtraction.from_rows(rows)
        except Exception:  # noqa: BLE001 — hosted flips degrade honestly
            placement_index = {}
        curve_index = None
        try:
            from kukai.ir.decompile.curve_extract import (
                build_curve_extract_cs, extract_curves)
            craw = await read_executor(build_curve_extract_cs(created_ids))
            curve_index = extract_curves(_peel(craw))
        except Exception:  # noqa: BLE001 — arc refinement degrades honestly
            curve_index = None
        curtain_index = None
        try:
            from kukai.ir.decompile.curtain_extract import (
                build_curtain_extract_cs, extract_curtain_topology)
            traw = await read_executor(build_curtain_extract_cs(created_ids))
            curtain_index = extract_curtain_topology(_peel(traw))
        except Exception:  # noqa: BLE001 — curtain panels degrade honestly
            curtain_index = None
        relifted = _op_leaves(list(lift_document(
            re_doc,
            profile_index=profile_index,
            family_placement_index=placement_index,
            wall_curve_index=curve_index,
            curtain_index=curtain_index)))

        # Debug evidence (fail-open): the created Δ-elements are deleted in the
        # ``finally`` cleanup, so without this dump a canon miss cannot be
        # diagnosed post-hoc — persist BOTH sides (payload + canon hash) plus
        # the raw re-extracted rows before the evidence is destroyed.
        if debug_dir:
            try:
                # НЕ импортировать здесь json: модуль уже импортирует его на
                # уровне файла, а повторный `import` внутри функции делает имя
                # ЛОКАЛЬНЫМ на всю функцию — и `json.dumps` в обработчике отказа
                # выше (ветка materialize_plan_refused) падал UnboundLocalError.
                # Замер 02.08 живьём на башне: вместо честного «материализованные
                # чанки не прошли typed KIR plan» с перечнем отказавших приходило
                # materialize_failed(UnboundLocalError), то есть тень импорта
                # превращала точный диагноз в крах и скрывала настоящую причину.
                import os as _os
                expected_debug_hashes = FidelityCanon.hash_sequence(
                    expected_leaves, _ORIGIN)
                relifted_debug_hashes = FidelityCanon.hash_sequence(
                    relifted, _ORIGIN)
                _os.makedirs(debug_dir, exist_ok=True)
                with open(_os.path.join(debug_dir, "idempotence_debug.json"),
                          "w", encoding="utf-8") as sink:
                    json.dump({
                        "delta_mm": list(delta_mm),
                        "canon_version": FIDELITY_CANON_VERSION,
                        "expected": [
                            {"hash": leaf_hash, "leaf": leaf}
                            for leaf, leaf_hash in zip(
                                expected_leaves, expected_debug_hashes)],
                        "relifted": [
                            {"hash": leaf_hash, "leaf": leaf}
                            for leaf, leaf_hash in zip(
                                relifted, relifted_debug_hashes)],
                        "reextracted_rows": [
                            element.to_dict() if hasattr(element, "to_dict")
                            else element for element in re_elements],
                        # Индекс витражей КОПИИ. Без него дыра «ячейка есть в
                        # переизвлечении, а листа нет» недоказуема посмертно:
                        # Δ-элементы удаляются в cleanup, и переспросить живую
                        # модель нечем. Fail-open: null — факт о прогоне.
                        "curtain_index": _jsonable(curtain_index),
                    }, sink, ensure_ascii=False)
            except Exception:  # noqa: BLE001 — debug must never break the run
                pass

        re_rows = [element.to_dict() if hasattr(element, "to_dict")
                   else element for element in re_elements]
        outside = modify_outside_universe(expected_leaves, re_rows)
        match, exp_hash, act_hash, per_kind, discrepancies = _compare(
            expected_leaves, relifted, outside)
        metrics = _percentages(per_kind)
        body = {
            "multiset_match": match,
            "expected_hash": exp_hash,
            "actual_hash": act_hash,
            "total_expected": metrics.total_expected,
            "total_actual": metrics.total_actual,
            "total_matched": metrics.total_matched,
            "total_extra": metrics.total_extra,
            # Legacy exact fields remain recall aliases for API compatibility.
            "raw_exact_pct": metrics.raw_recall_pct,
            "adjusted_exact_pct": metrics.adjusted_recall_pct,
            "raw_precision_pct": metrics.raw_precision_pct,
            "raw_recall_pct": metrics.raw_recall_pct,
            "adjusted_precision_pct": metrics.adjusted_precision_pct,
            "adjusted_recall_pct": metrics.adjusted_recall_pct,
            "comparable_coverage_pct": _ratio_pct(
                metrics.total_matched + form_accepted, non_datum_total),
            "atoms_escrowed": atoms_escrowed,
            "atoms_form_accepted": form_accepted,
            "atoms_form_rejected": form_rejected,
            "atoms_form_inconclusive": form_inconclusive,
            "form_expectations": tuple(
                record.as_dict() for record in escrow_records),
            "form_acceptance": form_verdict_rows,
            "form_read_error": form_read_error,
            "per_kind": tuple(per_kind),
            "discrepancies": tuple(discrepancies),
            "isolated_failures": tuple(isolated_failures),
            "chunk_failures": tuple(chunk_failures),
            "op_refusals": tuple(op_refusals),
        }
        if recovery is not None:
            await recovery.after_compared({
                **body,
                "doc_stamp": doc_stamp,
                "delta_mm": list(delta_mm),
                "per_kind": [item.to_dict() for item in per_kind],
                "discrepancies": list(discrepancies),
                "comparison_performed": True,
                "datums_skipped": datums_skipped,
                "atoms_excluded": atoms_excluded,
                "atoms_escrowed": atoms_escrowed,
                "atoms_form_accepted": form_accepted,
                "atoms_form_rejected": form_rejected,
                "atoms_form_inconclusive": form_inconclusive,
                "form_expectations": list(body["form_expectations"]),
                "form_acceptance": list(form_verdict_rows),
                "form_read_error": form_read_error,
                "non_datum_total": non_datum_total,
                "canon_version": FIDELITY_CANON_VERSION,
            })
    except IdempotenceError as exc:
        pending_error = exc
    except Exception as exc:  # noqa: BLE001 — absolute fail-closed
        pending_error = IdempotenceError(
            "internal", "внутренняя ошибка A5", repr(exc))
    finally:
        # Cleanup ALWAYS runs on the live path — orphaned Δ-elements are
        # inadmissible.  It runs here (inside the same coroutine, before we
        # build the final report) so the report can carry its true outcome, and
        # it runs whether the try body succeeded or raised.
        keep_complete_delta = bool(
            created_ids and keep_delta and pending_error is None)
        if recovery is not None and pending_error is None:
            recovery_cleanup_started = True
            try:
                await recovery.before_cleanup(
                    created_ids, retain=keep_complete_delta)
            except Exception as exc:  # recovery uncertainty is a typed failure
                pending_error = IdempotenceError(
                    "recovery_transition_failed",
                    "durable A5 cleanup preview не подтверждён", repr(exc))
                keep_complete_delta = False
        if keep_complete_delta:
            # Оператор просил РАЗ увидеть реконструкцию — оставляем Δ-элементы
            # на +200м (видно рядом с оригиналом), зачистка не запускается.
            # Их exact run prefix возвращается вызывающему; удалить их может
            # только явный preview+confirm вызов cleanup_stamps для этого run.
            cleanup_ok, cleanup_detail = True, (
                # Расстояние берётся из фактического Δ, а не из константы:
                # смещение стало параметром, и зашитые «+200м» сообщали бы
                # оператору неправду о том, где искать копию.
                f"KEEP: {len(created_ids)} Δ-элементов ОСТАВЛЕНЫ со сдвигом "
                f"({delta_mm[0] / 1000.0:g}, {delta_mm[1] / 1000.0:g}, "
                f"{delta_mm[2] / 1000.0:g}) м "
                "(смотри рядом с оригиналом; убрать — cleanup_stamps)")
        elif created_ids:
            cleanup_ok, cleanup_detail = await cleanup_created(
                created_ids, delete_runner)
        else:
            cleanup_ok, cleanup_detail = True, "nothing to clean up"
        if not keep_complete_delta and sweep_runner is not None:
            try:
                sweep_envelope = await sweep_runner()
                sweep_ok = (
                    isinstance(sweep_envelope, Mapping)
                    and sweep_envelope.get("ok") is True)
                census = _stamp_census(sweep_envelope)
                if (not cleanup_ok and sweep_ok and census is not None
                        and census["remaining"] == 0):
                    # Поштучный проход не досчитался элементов, а перепись
                    # говорит, что НАШЕГО в модели не осталось. Это не
                    # смягчение закона, а ответ на его настоящий вопрос:
                    # каскадно удалённый вместе с хозяином элемент
                    # ОТСУТСТВУЕТ — ровно то, ради чего уборка и была.
                    cleanup_ok = True
                    cleanup_detail += (
                        "; перепись штампа: 0 остатков — недосчитанные id "
                        "исчезли вместе со своими хозяевами, в модели "
                        "нашего не осталось")
                else:
                    cleanup_ok = cleanup_ok and sweep_ok
                cleanup_detail += f"; run sweep: {_short(sweep_envelope)}"
            except Exception as exc:  # noqa: BLE001 — uncertainty is failure
                cleanup_ok = False
                cleanup_detail += f"; run sweep failed: {exc!r}"
        if recovery is not None and (created_ids or recovery_cleanup_started):
            try:
                await recovery.after_cleanup(
                    created_ids, retain=keep_complete_delta,
                    cleanup_ok=cleanup_ok, cleanup_detail=cleanup_detail)
            except Exception as exc:  # durable completion proof is mandatory
                cleanup_ok = False
                cleanup_detail += f"; recovery completion failed: {exc!r}"

    # A failure that occurred after ids were created still reports those ids and
    # the (now-completed) cleanup outcome, so the operator sees both.
    if pending_error is not None:
        return _errored(
            doc_stamp, delta_mm, expected_hash, len(op_leaves), datums_skipped,
            pending_error, dry_run=False, created_ids=tuple(created_ids),
            cleanup_ok=cleanup_ok, cleanup_detail=cleanup_detail,
            atoms_excluded=atoms_excluded,
            atoms_escrowed=atoms_escrowed,
            atoms_form_accepted=form_accepted,
            atoms_form_rejected=form_rejected,
            atoms_form_inconclusive=form_inconclusive,
            form_expectations=tuple(
                record.as_dict() for record in escrow_records),
            form_acceptance=form_verdict_rows,
            form_read_error=form_read_error,
            isolated_failures=tuple(isolated_failures),
            chunk_failures=tuple(chunk_failures),
            op_refusals=tuple(op_refusals))

    assert body is not None  # unreachable: no error means body was built
    return IdempotenceReport(
        doc_stamp=doc_stamp,
        delta_mm=delta_mm,
        multiset_match=bool(body["multiset_match"]),
        expected_hash=str(body["expected_hash"]),
        actual_hash=str(body["actual_hash"]),
        total_expected=int(body["total_expected"]),
        total_actual=int(body["total_actual"]),
        total_matched=int(body["total_matched"]),
        total_extra=int(body["total_extra"]),
        raw_exact_pct=body["raw_exact_pct"],
        adjusted_exact_pct=body["adjusted_exact_pct"],
        raw_precision_pct=body["raw_precision_pct"],
        raw_recall_pct=body["raw_recall_pct"],
        adjusted_precision_pct=body["adjusted_precision_pct"],
        adjusted_recall_pct=body["adjusted_recall_pct"],
        per_kind=body["per_kind"],
        discrepancies=body["discrepancies"],
        datums_skipped=datums_skipped,
        modify_outside_universe=sum(
            int(getattr(k, "outside_universe", 0)) for k in body["per_kind"]),
        modify_outside_universe_by_op=tuple(
            {"op_name": k.op_name, "count": int(k.outside_universe)}
            for k in body["per_kind"]
            if int(getattr(k, "outside_universe", 0))),
        atoms_excluded=atoms_excluded,
        atoms_escrowed=int(body["atoms_escrowed"]),
        atoms_form_accepted=int(body["atoms_form_accepted"]),
        atoms_form_rejected=int(body["atoms_form_rejected"]),
        atoms_form_inconclusive=int(body["atoms_form_inconclusive"]),
        form_expectations=body["form_expectations"],
        form_acceptance=body["form_acceptance"],
        form_read_error=str(body["form_read_error"]),
        non_datum_total=non_datum_total,
        comparable_coverage_pct=body["comparable_coverage_pct"],
        created_ids=tuple(created_ids),
        cleanup_ok=cleanup_ok,
        cleanup_detail=cleanup_detail,
        dry_run=False,
        isolated_failures=tuple(body.get("isolated_failures") or ()),
        chunk_failures=tuple(body.get("chunk_failures") or ()),
        op_refusals=tuple(body.get("op_refusals") or ()),
    )


def _errored(
    doc_stamp: str,
    delta_mm: Vec3,
    expected_hash: str,
    total_expected: int,
    datums_skipped: int,
    error: IdempotenceError,
    *,
    dry_run: bool,
    created_ids: tuple[str, ...] = (),
    cleanup_ok: bool = True,
    cleanup_detail: str = "see error",
    atoms_excluded: int = 0,
    atoms_escrowed: int = 0,
    atoms_form_accepted: int = 0,
    atoms_form_rejected: int = 0,
    atoms_form_inconclusive: int = 0,
    form_expectations: tuple[dict[str, Any], ...] = (),
    form_acceptance: tuple[dict[str, Any], ...] = (),
    form_read_error: str = "",
    isolated_failures: tuple[dict[str, Any], ...] = (),
    chunk_failures: tuple[dict[str, Any], ...] = (),
    op_refusals: tuple[dict[str, Any], ...] = (),
) -> IdempotenceReport:
    return IdempotenceReport(
        doc_stamp=doc_stamp,
        delta_mm=delta_mm,
        multiset_match=None,
        expected_hash=expected_hash,
        actual_hash="",
        total_expected=total_expected,
        total_matched=0,
        raw_exact_pct=None,
        adjusted_exact_pct=None,
        per_kind=(),
        discrepancies=(),
        datums_skipped=datums_skipped,
        atoms_excluded=atoms_excluded,
        atoms_escrowed=atoms_escrowed,
        atoms_form_accepted=atoms_form_accepted,
        atoms_form_rejected=atoms_form_rejected,
        atoms_form_inconclusive=atoms_form_inconclusive,
        form_expectations=form_expectations,
        form_acceptance=form_acceptance,
        form_read_error=form_read_error,
        non_datum_total=total_expected + atoms_excluded + atoms_escrowed,
        comparable_coverage_pct=None,
        created_ids=created_ids,
        cleanup_ok=cleanup_ok,
        cleanup_detail=cleanup_detail,
        dry_run=dry_run,
        error=error.to_dict(),
        isolated_failures=isolated_failures,
        chunk_failures=chunk_failures,
        op_refusals=op_refusals,
    )


__all__ = [
    "DELTA_MM",
    "EXPECTED_DISCREPANCY_OPS",
    "IdempotenceError",
    "IdempotenceReport",
    "KindComparison",
    "MetricTotals",
    "SafetyContext",
    "SweepRunner",
    "REBUILD_PLAN_VERSION",
    "build_rebuild_plan",
    "build_reextract_cs",
    "cleanup_created",
    "collect_created_by_op",
    "collect_created_ids",
    "run_idempotence",
]
