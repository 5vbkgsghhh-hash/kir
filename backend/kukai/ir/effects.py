"""Effect typing + deterministic parallelism for the forward IR (wave 8).

Ops declare their read/write sets, so INDEPENDENT ops can be safely
auto-parallelized at emission and data races are detected STATICALLY.  The
effect signature of a grounded op is derived from what it already declares:

* **writes** = ``{op.id}`` — the op materializes an element addressed by its own
  id (the validator guarantees ids are unique, so write-sets are normally
  disjoint);
* **reads** = ``authoring._op_refs(op)`` — the intra-program op ids it depends on
  (a window's host wall, a level a wall stands on, an annotation's target);
* **external_reads** = pinned element ids (a ``set_param`` target that already
  exists) — read-only on something the program does not create.

Op B depends on A (``A -> B``) when ``B.reads ∩ A.writes != {}`` (B reads what A
writes: a window reads its host wall).  From that dependency DAG a deterministic
**wave schedule** is built (topological levels): ops in the same wave are
mutually independent, hence safe to emit/run in parallel.  A cycle is an
``EffectCycleError``.

**Two facts used to share the name ``WriteWriteConflict``, and only one of them
can happen (measured 2026-08-10).**  ``build_dependency_graph`` checks the input
for a duplicate op id FIRST, and that check dominates the write-write scan
completely: ``writes`` is exactly ``{op_id}``, so two ops can share a written id
only by sharing their op id — which the first check has already refused.  The
write-write scan is therefore UNREACHABLE today, and the failure a caller
actually meets is "you handed me a malformed op list", which is a different fact
from "two ops race".  They are named apart now: :class:`DuplicateOpId` (a
subclass, so nothing that caught the old name stops catching it) for the input,
:class:`WriteWriteConflict` for the race.  The scan is kept rather than deleted
because it becomes LIVE the moment ``writes`` stops being a singleton of the op
id — an op that writes an external target would put it back in service — and
``test_write_write_is_dominated_by_the_id_check`` fails when that day comes, so
nobody restores the race guard by accident and nobody deletes it either.

T-SCHED: any linear order that respects the waves is valid and equivalent —
independent ops commute (no ref, no shared write between them, by construction).

Discipline (forks in EFFECT_TYPING_SPEC.md): we model the EXPLICIT IR
dependencies (refs), not hidden Revit side effects (auto-join); conservatively,
doubt becomes a dependency (two writes to one external target serialize).
Inert, additive, opt-in (``effects_enabled()`` default OFF; authoring/spec
untouched).  Frozen L0 untouched.
"""
from __future__ import annotations

import os
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from kukai.ir import spec
from kukai.ir.authoring import _op_refs


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class EffectError(ValueError):
    """Base for every typed effect-layer failure."""


class EffectCycleError(EffectError):
    """The dependency graph has a cycle (unschedulable)."""


class WriteWriteConflict(EffectError):
    """Two ops write the same id with no order between them (static race).

    UNREACHABLE while ``writes == {op_id}`` — see the module docstring.  Kept
    because it returns to service the moment an op writes anything else.
    """


class DuplicateOpId(WriteWriteConflict):
    """The op list itself carries one id twice.

    This is the failure a caller actually meets, and it is NOT a race: it says
    the list was never validated (``midend`` refuses with "planned op ids must
    be unique"), not that two independent ops collided.  Subclasses
    :class:`WriteWriteConflict` so every existing handler keeps working.
    """


# ---------------------------------------------------------------------------
# Flag (inertness contract)
# ---------------------------------------------------------------------------


def effects_enabled() -> bool:
    """Opt-in gate for future pipeline wiring; default OFF."""

    return os.getenv("KUKAI_IR_EFFECTS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ---------------------------------------------------------------------------
# Effect signature
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EffectSignature:
    op_id: str
    op_name: str
    writes: frozenset[str]
    reads: frozenset[str]
    external_reads: frozenset[str]
    writes_model: bool


def _external_reads(op: Mapping[str, Any], op_ids: frozenset[str]) -> frozenset[str]:
    """Pinned element ids the op reads that are NOT intra-program ops."""

    found: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, Mapping):
            # A pinned target/selector: {"by": "element_id", "value": <int|str>}
            if node.get("by") == "element_id" and "value" in node:
                found.add(f"external:{node['value']}")
            for key, value in node.items():
                if key == "__host_wall__":
                    continue
                _walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                _walk(value)

    _walk(op)
    return frozenset(found)


def effect_signature(
    grounded_op: Mapping[str, Any], op_ids: frozenset[str] | None = None,
) -> EffectSignature:
    """Derive the read/write effect signature of one grounded op."""

    if not isinstance(grounded_op, Mapping) or "op" not in grounded_op \
            or "id" not in grounded_op:
        raise EffectError("effect_signature needs a grounded op with op/id")
    op_name = grounded_op["op"]
    op_id = grounded_op["id"]
    op_spec = spec.OPS.get(op_name)
    writes_model = bool(op_spec.writes_model) if op_spec is not None else False

    ids = op_ids if op_ids is not None else frozenset()
    refs = frozenset(_op_refs(grounded_op))
    # Only intra-program refs count as reads-of-writes; unknown ids are treated
    # as external (they are not produced by this program).
    intra = refs & ids if ids else refs
    external = _external_reads(grounded_op, ids)

    # A write op writes its own id; a query op writes nothing.
    writes = frozenset({op_id}) if writes_model else frozenset()
    return EffectSignature(
        op_id=op_id,
        op_name=op_name,
        writes=writes,
        reads=intra,
        external_reads=external,
        writes_model=writes_model,
    )


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Dependency:
    before: str
    after: str
    reason: str   # "reads_write" | "shared_external_write" | "order"


def build_dependency_graph(
    grounded_ops: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, EffectSignature], list[Dependency]]:
    """Return (signatures by id, dependency edges).

    ``A -> B`` when B reads what A writes.  Two write ops that would write the
    same id with no program order are a ``WriteWriteConflict``.  Two write ops
    touching the same EXTERNAL target are conservatively serialized in program
    order (a shared-external-write dependency).
    """

    op_ids = frozenset(op["id"] for op in grounded_ops)
    if len(op_ids) != len(grounded_ops):
        raise DuplicateOpId(
            "duplicate op id: the op list was not validated (midend refuses "
            "this with \"planned op ids must be unique\"); two ops would write "
            "the same identity")

    order = {op["id"]: index for index, op in enumerate(grounded_ops)}
    signatures = {
        op["id"]: effect_signature(op, op_ids) for op in grounded_ops
    }

    writer_of: dict[str, str] = {}
    for op in grounded_ops:
        sig = signatures[op["id"]]
        for written in sig.writes:
            if written in writer_of and writer_of[written] != op["id"]:
                # UNREACHABLE while writes == {op_id}: reaching here needs two
                # DIFFERENT op ids writing ONE id, and the duplicate-id check
                # above has already refused the only way that can happen.
                # Pinned by test_write_write_is_dominated_by_the_id_check.
                raise WriteWriteConflict(
                    f"ops {writer_of[written]!r} and {op['id']!r} both write "
                    f"{written!r}")
            writer_of[written] = op["id"]

    deps: list[Dependency] = []
    seen: set[tuple[str, str]] = set()

    # reads-of-writes: B reads an id that A writes.
    for op in grounded_ops:
        sig = signatures[op["id"]]
        for read in sig.reads:
            producer = writer_of.get(read)
            if producer is not None and producer != op["id"]:
                edge = (producer, op["id"])
                if edge not in seen:
                    seen.add(edge)
                    deps.append(Dependency(
                        before=producer, after=op["id"], reason="reads_write"))

    # shared external write: two write ops touching the same external target
    # are serialized by program order (conservative, Р5).
    external_writers: dict[str, list[str]] = defaultdict(list)
    for op in grounded_ops:
        sig = signatures[op["id"]]
        if sig.writes_model:
            for ext in sig.external_reads:
                external_writers[ext].append(op["id"])
    for ext, writers in external_writers.items():
        if len(writers) < 2:
            continue
        ordered = sorted(writers, key=lambda oid: order[oid])
        for before, after in zip(ordered, ordered[1:]):
            edge = (before, after)
            if edge not in seen:
                seen.add(edge)
                deps.append(Dependency(
                    before=before, after=after,
                    reason="shared_external_write"))

    deps.sort(key=lambda d: (d.before, d.after))
    return signatures, deps


# ---------------------------------------------------------------------------
# Parallel schedule (wave topological levels)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScheduleWave:
    index: int
    op_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParallelSchedule:
    waves: tuple[ScheduleWave, ...]
    dependencies: tuple[Dependency, ...]

    @property
    def max_parallelism(self) -> int:
        return max((len(wave.op_ids) for wave in self.waves), default=0)

    @property
    def critical_path(self) -> int:
        return len(self.waves)

    @property
    def is_parallel(self) -> bool:
        return any(len(wave.op_ids) > 1 for wave in self.waves)

    def linear_order(self) -> tuple[str, ...]:
        return tuple(
            op_id for wave in self.waves for op_id in wave.op_ids)

    def wave_of(self, op_id: str) -> int:
        for wave in self.waves:
            if op_id in wave.op_ids:
                return wave.index
        raise EffectError(f"op {op_id!r} not in schedule")


def schedule(grounded_ops: Sequence[Mapping[str, Any]]) -> ParallelSchedule:
    """Deterministic wave schedule; ops in one wave are independent (parallel).

    Kahn topological levelling: wave 0 = ops with no dependency; wave k = ops
    all of whose predecessors are in earlier waves.  Within a wave, ops are
    sorted by id (reproducible).  A cycle raises ``EffectCycleError``.
    """

    signatures, deps = build_dependency_graph(grounded_ops)
    all_ids = [op["id"] for op in grounded_ops]

    successors: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {op_id: 0 for op_id in all_ids}
    for dep in deps:
        successors[dep.before].append(dep.after)
        indegree[dep.after] += 1

    waves: list[ScheduleWave] = []
    ready = sorted(op_id for op_id in all_ids if indegree[op_id] == 0)
    scheduled = 0
    wave_index = 0
    while ready:
        wave = tuple(sorted(ready))
        waves.append(ScheduleWave(index=wave_index, op_ids=wave))
        scheduled += len(wave)
        next_ready: list[str] = []
        for op_id in wave:
            for succ in successors[op_id]:
                indegree[succ] -= 1
                if indegree[succ] == 0:
                    next_ready.append(succ)
        ready = sorted(next_ready)
        wave_index += 1

    if scheduled != len(all_ids):
        raise EffectCycleError(
            "dependency graph has a cycle; cannot build a wave schedule")

    return ParallelSchedule(waves=tuple(waves), dependencies=tuple(deps))


def conflicts(grounded_ops: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Detect static races (write-write / cycles) without raising."""

    problems: list[str] = []
    try:
        schedule(grounded_ops)
    except WriteWriteConflict as exc:
        problems.append(f"write_write: {exc}")
    except EffectCycleError as exc:
        problems.append(f"cycle: {exc}")
    return tuple(problems)


__all__ = [
    "Dependency",
    "DuplicateOpId",
    "EffectCycleError",
    "EffectError",
    "EffectSignature",
    "ParallelSchedule",
    "ScheduleWave",
    "WriteWriteConflict",
    "build_dependency_graph",
    "conflicts",
    "effect_signature",
    "effects_enabled",
    "schedule",
]
