"""Проводка слоя `rebuild` наружу: пересборка ДЕЛЬТОЙ, а не всем зданием.

`rebuild.py` умеет превратить различие двух разборов в исполнимую типизованную
дельту (`delta_between`) и доказать переход `apply(state(A), Δ) == state(B)`
(`assert_transition`).  Чего он НЕ умеет — назвать материализатору, какие
именно листья B надо переводить в программы.  Ровно этого не хватало: 362
строки и 14 тестов лежали на складе с собственной пометкой докстринга
«opt-in gate for future pipeline wiring», а единственный живой вход пересборки
(`serving.handle_revit_rebuild`) каждый раз брал ВСЕ листья `tree.json` — то
есть строил здание целиком даже тогда, когда рядом лежал прошлый разбор того
же здания.

Этот модуль ничего нового не считает.  Он живёт между `rebuild` и двумя его
потребителями:

* `ir/serving.py::handle_revit_rebuild` — живой путь: при флаге
  `KUKAI_IR_REBUILD` и явно названном `base_doc_stamp` пересборка
  материализует ПОДМНОЖЕСТВО листьев B вместо всего дерева;
* `tools/kir_rebuild.py` — прибор оператора: тот же план по двум сохранённым
  разборам, без Revit и без флага (инструмент, а не поведение).

ЗАМЫКАНИЕ ПО ССЫЛКАМ — ПОЧЕМУ ДЕЛЬТЫ ОДНОЙ КЛАССИФИКАЦИИ НЕ ХВАТАЕТ.
Материализатор разрешает `{"ref": <l1_id>}` только ВНУТРИ прогона: ссылка,
чья цель не материализуется, снимает и сам оп — типизованным пропуском
`host_unmaterialized` (см. `materialize.leaves_to_program`, цикл до
неподвижной точки).  Значит наивная дельта «только изменившиеся листья»
МОЛЧА теряет ровно то, что оператор и правил: изменившаяся дверь в
неизменной стене осталась бы пропуском.  Поэтому набор на материализацию
замыкается по неориентированному графу `ref` — той же связной компонентой,
которую материализатор считает неделимой (Д5a).

Замыкание НЕ ломает теорему T-APPLY, и это проверяется, а не обещается: за
каждый втянутый неизменный лист X в дельту дописывается пара «снять X» +
«поставить X» (`refresh`), на мультимножестве дающая ноль, после чего
`assert_transition` прогоняется на РАСШИРЕННОЙ программе.  Если A не тот —
`apply_delta` отказывает типизованно (`DeltaApplyError`), и это единственный
правильный исход: дельта, применённая не к своему A, — молчаливо неверный
результат, то есть нарушение главного инварианта.

Обход ссылок берётся у материализатора (`_iter_refs`), а не пишется заново:
это ЕДИНСТВЕННЫЙ авторитет по тому, что вообще является ссылкой, и два
разошедшихся обхода были бы хуже, чем ни одного.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from kukai.ir.decompile.fold import TreeNode, canon_op, iter_l1_leaves
from kukai.ir.decompile.l1_schema import L1Node
from kukai.ir.decompile.materialize import _iter_refs
from kukai.ir.decompile.rebuild import (
    DeltaOp,
    DeltaProgram,
    assert_transition,
    delta_between,
)

REBUILD_PLAN_SCHEMA = "kir-rebuild-plan/1"

_ZERO = (0.0, 0.0, 0.0)

__all__ = [
    "REBUILD_PLAN_SCHEMA",
    "DeltaRebuildPlan",
    "delta_rebuild_plan",
    "plan_refusal",
    "plan_report",
]


@dataclass(frozen=True, slots=True)
class DeltaRebuildPlan:
    """Что именно материализовать, чтобы из здания A получилось здание B."""

    program: DeltaProgram
    # Листья B, которые дельта назвала сама (emit + relocate).
    emit_source_ids: frozenset[str]
    # Листья B, втянутые замыканием по `ref`: сами не менялись, но делят
    # связную компоненту с изменившимися и без них ссылка не разрешится.
    closure_source_ids: frozenset[str]
    # Листья A, которых в B больше нет (или чьё содержимое сменилось).
    retire_source_ids: tuple[str, ...]
    leaves_total_a: int
    leaves_total_b: int

    @property
    def materialize_source_ids(self) -> frozenset[str]:
        return self.emit_source_ids | self.closure_source_ids

    @property
    def materialize_total(self) -> int:
        return len(self.emit_source_ids) + len(self.closure_source_ids)

    @property
    def is_empty(self) -> bool:
        """Здания совпали: материализовать нечего и снимать нечего."""

        return not self.materialize_source_ids and not self.retire_source_ids


def _op_leaves_by_id(leaves: Iterable[L1Node]) -> dict[str, L1Node]:
    return {leaf["_id"]: leaf for leaf in leaves if leaf["kind"] == "op"}


def _close_over_refs(
    by_l1_id: dict[str, L1Node], seeds: frozenset[str],
) -> frozenset[str]:
    """Замкнуть набор `source_element_id` по неориентированному графу `ref`.

    Возвращает ДОБАВКУ (без самих семян), чтобы вызывающий видел цену
    замыкания отдельным числом: замыкание, которого не видно, — это тихий
    рост дельты, а именно ради её размера всё и затевалось.
    """

    adjacency: dict[str, set[str]] = {leaf_id: set() for leaf_id in by_l1_id}
    for leaf_id, leaf in by_l1_id.items():
        for target in _iter_refs(leaf["params"]):
            if target in by_l1_id and target != leaf_id:
                adjacency[leaf_id].add(target)
                adjacency[target].add(leaf_id)

    seed_l1_ids = [
        leaf_id for leaf_id, leaf in by_l1_id.items()
        if leaf["source_element_id"] in seeds
    ]
    visited: set[str] = set(seed_l1_ids)
    stack = list(seed_l1_ids)
    while stack:
        current = stack.pop()
        for neighbour in adjacency[current]:
            if neighbour not in visited:
                visited.add(neighbour)
                stack.append(neighbour)
    return frozenset(
        by_l1_id[leaf_id]["source_element_id"] for leaf_id in visited
    ) - seeds


def _refresh_ops(leaves: Iterable[L1Node]) -> tuple[DeltaOp, ...]:
    """Пара «снять X» + «поставить X» на каждый втянутый неизменный лист.

    На мультимножестве это ноль, поэтому T-APPLY сохраняется; но снятие
    проходит через тот же `apply_delta`, а значит замыкание НЕ может втянуть
    элемент, которого в состоянии A не было, — отказ будет типизованным.
    """

    ops: list[DeltaOp] = []
    for leaf in leaves:
        canonical = canon_op(leaf, _ZERO)
        source_id = leaf["source_element_id"]
        ops.append(DeltaOp(
            kind="retire", reason="refresh", path=None, hash=None,
            remove_ops=(canonical,), add_ops=(),
            remove_source_ids=(source_id,), add_source_ids=()))
        ops.append(DeltaOp(
            kind="emit", reason="refresh", path=None, hash=None,
            remove_ops=(), add_ops=(canonical,),
            remove_source_ids=(), add_source_ids=(source_id,)))
    return tuple(ops)


def delta_rebuild_plan(
    tree_a: TreeNode,
    tree_b: TreeNode,
    *,
    label_a: str = "a",
    label_b: str = "b",
) -> DeltaRebuildPlan:
    """Дельта A→B, замкнутая по ссылкам и ДОКАЗАННАЯ на состояниях.

    Поднимает `RebuildError`/`DeltaApplyError`, если дельта не переводит
    состояние A в состояние B: провалить громко здесь дешевле, чем построить
    в живой модели половину здания.
    """

    program = delta_between(tree_a, tree_b, label_a=label_a, label_b=label_b)

    emit_ids: set[str] = set()
    retire_ids: set[str] = set()
    for op in program.ops:
        if op.kind in ("emit", "relocate"):
            emit_ids.update(op.add_source_ids)
        if op.kind in ("retire", "relocate"):
            retire_ids.update(op.remove_source_ids)

    leaves_b = list(iter_l1_leaves(tree_b))
    by_l1_id = _op_leaves_by_id(leaves_b)
    closure_ids = _close_over_refs(by_l1_id, frozenset(emit_ids))

    # Расширенная программа проверяется целиком — вместе с добавкой замыкания.
    # Порядок `retire → relocate → emit` уже задан `_ORDER` в `rebuild.py`, и
    # `apply_delta` идёт по списку как он лежит, поэтому пересортировка здесь
    # не нужна: `build_delta` отдал ops отсортированными, а `refresh`-пары
    # доклеиваются после и снимают/ставят один и тот же токен.
    closure_leaves = [
        leaf for leaf in by_l1_id.values()
        if leaf["source_element_id"] in closure_ids
    ]
    closed = DeltaProgram(
        ops=tuple(sorted(
            program.ops + _refresh_ops(closure_leaves),
            key=lambda op: (0 if op.kind == "retire"
                            else 1 if op.kind == "relocate" else 2,
                            op.path or (), op.hash or ""))),
        reused_count=program.reused_count,
        base_fidelity_hash=program.base_fidelity_hash,
        target_fidelity_hash=program.target_fidelity_hash,
    )
    assert_transition(closed, tree_a, tree_b)

    return DeltaRebuildPlan(
        program=closed,
        emit_source_ids=frozenset(emit_ids),
        closure_source_ids=closure_ids,
        retire_source_ids=tuple(sorted(retire_ids)),
        leaves_total_a=sum(1 for _ in iter_l1_leaves(tree_a)),
        leaves_total_b=len(leaves_b),
    )


def plan_report(plan: DeltaRebuildPlan) -> dict[str, Any]:
    """JSON-совместимая сводка плана.  Числа, а не прилагательные."""

    return {
        "schema": REBUILD_PLAN_SCHEMA,
        "ok": True,
        "leaves_a": plan.leaves_total_a,
        "leaves_b": plan.leaves_total_b,
        # Сколько листьев B пришлось бы строить полной материализацией.
        "full_leaves": plan.leaves_total_b,
        # Сколько строит дельта: названные дельтой + втянутые замыканием.
        "delta_leaves": plan.materialize_total,
        "delta_named": len(plan.emit_source_ids),
        "delta_ref_closure": len(plan.closure_source_ids),
        "retire_leaves": len(plan.retire_source_ids),
        "reused_leaves": plan.program.reused_count,
        "identical": plan.is_empty,
    }


def plan_refusal(exc: BaseException) -> dict[str, Any]:
    """Отказ, который видно.  Никогда не притворяется пустой дельтой.

    Пустой набор при `ok:true` значит «здания совпали», при `ok:false` —
    «посчитать не удалось», и путать их нельзя: именно так «дельта пуста»
    однажды становится отчётом о сломанном приборе.
    """

    return {
        "schema": REBUILD_PLAN_SCHEMA,
        "ok": False,
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }
