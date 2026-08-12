"""Отчёт слоя `merkle` по СВЁРНУТОМУ дереву — единственный провод наружу.

`merkle.py` считает адрес содержимого (`build_index`), повторы
(`dedup_report`) и различие двух зданий (`diff_trees`).  Что он НЕ умеет —
превратить это в артефакт, который кто-нибудь прочитает.  Ровно этого не
хватало: 1312 строк и 41 тест лежали на складе с собственной пометкой
докстринга «nothing in the pipeline imports this module».

Этот модуль не считает НИЧЕГО нового.  Он сериализует уже посчитанное в
JSON-совместимый словарь и живёт между `merkle` и двумя его потребителями:

* `decompile/pipeline.py` — живой путь: после `tree.json` кладёт рядом
  `merkle.json` (флаг `KUKAI_IR_MERKLE`, по умолчанию ВЫКЛ);
* `tools/kir_merkle.py` — прибор оператора: тот же отчёт и РАЗЛИЧИЕ двух
  сохранённых разборов, без Revit и без флага (инструмент, а не поведение).

ЗАКОН ОТЧЁТА: молчания нет.  `ok:false` с типом и текстом отказа — это НЕ
то же самое, что пустой список повторов или пустое различие, и по файлу
одно от другого обязано отличаться с первого взгляда.  Пустой `entries`
при `ok:true` значит «здания совпали», при `ok:false` — «посчитать не
удалось», и путать их нельзя: именно так «дедупликация ничего не нашла»
однажды становится отчётом о сломанном приборе.

Полнота вместо усечения: список повторов пишется ЦЕЛИКОМ.  Он на три
порядка меньше самого `tree.json` (замер 09.08.2026: 232 записи против
30 МБ дерева у `snowdon_plumb_v4`), а обрезанный список — это тихая ложь о
том, сколько повторов в здании.
"""
from __future__ import annotations

from typing import Any

from kukai.ir.decompile.fold import TreeNode
from kukai.ir.decompile.merkle import (
    MERKLE_VERSION,
    MerkleError,
    MerkleIndex,
    build_index,
    dedup_report,
    diff_trees,
)

REPORT_SCHEMA = "kir-merkle-report/1"
DIFF_SCHEMA = "kir-merkle-diff/1"

__all__ = [
    "DIFF_SCHEMA",
    "REPORT_SCHEMA",
    "building_report",
    "diff_report",
]


def _refusal(schema: str, exc: BaseException, **extra: Any) -> dict[str, Any]:
    """Отказ, который видно.  Никогда не притворяется пустым результатом."""

    return {
        "schema": schema,
        "merkle_version": MERKLE_VERSION,
        "ok": False,
        "error": {"type": type(exc).__name__, "message": str(exc)},
        **extra,
    }


def _index(tree: TreeNode, label: str) -> MerkleIndex:
    return build_index(tree, label=label)


def building_report(tree: Any, *, label: str = "") -> dict[str, Any]:
    """Адрес содержимого здания + полный список повторяющихся поддеревьев.

    `savings` одной записи — сколько листьев не пришлось бы строить заново,
    если бы форму рисовали один раз и размещали `occurrences` раз.  Записи,
    целиком лежащие внутри других повторов (санузел внутри повторяющейся
    квартиры), `dedup_report` прячет по умолчанию — иначе экономия считается
    дважды.
    """

    try:
        index = _index(tree, label)
        repeats = dedup_report([index])
    except (MerkleError, KeyError, TypeError, ValueError) as exc:
        return _refusal(REPORT_SCHEMA, exc, label=label)

    entries = [
        {
            "hash": entry.hash,
            "kind": entry.kind,
            "label": entry.sample_label,
            "leaf_count": entry.leaf_count,
            "occurrences": entry.occurrence_count,
            "savings": entry.savings,
        }
        for entry in repeats
    ]
    return {
        "schema": REPORT_SCHEMA,
        "merkle_version": MERKLE_VERSION,
        "ok": True,
        "label": label,
        "root_hash": index.root_hash,
        "root_origin_mm": list(index.root_origin),
        "nodes": index.node_count,
        "distinct_nodes": index.distinct_count,
        # Во сколько раз DAG компактнее дерева. 1.0 — повторов нет вовсе.
        "share_ratio": (round(index.node_count / index.distinct_count, 3)
                        if index.distinct_count else 0.0),
        "repeats": entries,
        "repeats_total": len(entries),
        "leaves_saved": sum(entry.savings for entry in repeats),
    }


def _side(index: MerkleIndex) -> dict[str, Any]:
    return {
        "label": index.label,
        "root_hash": index.root_hash,
        "nodes": index.node_count,
        "distinct_nodes": index.distinct_count,
    }


def diff_report(
    tree_a: Any,
    tree_b: Any,
    *,
    label_a: str = "a",
    label_b: str = "b",
) -> dict[str, Any]:
    """Различие двух свёрнутых зданий: что появилось, ушло, изменилось, уехало.

    `pruned` — сколько поддеревьев совпало по хешу и было отсечено целиком,
    не спускаясь внутрь.  Это и есть выигрыш адреса содержимого: неизменная
    часть здания не перечитывается поэлементно.
    """

    try:
        index_a = _index(tree_a, label_a)
        index_b = _index(tree_b, label_b)
        diff = diff_trees(index_a, index_b)
    except (MerkleError, KeyError, TypeError, ValueError) as exc:
        return _refusal(DIFF_SCHEMA, exc, a={"label": label_a},
                        b={"label": label_b})

    counts: dict[str, int] = {
        "added": 0, "removed": 0, "changed": 0, "moved": 0}
    for entry in diff.entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1

    return {
        "schema": DIFF_SCHEMA,
        "merkle_version": MERKLE_VERSION,
        "ok": True,
        "a": _side(index_a),
        "b": _side(index_b),
        # Совпадение КОРНЕВЫХ хешей — единственное честное «здания равны».
        "identical": index_a.root_hash == index_b.root_hash,
        "pruned": diff.pruned,
        "unchanged_subtrees": len(diff.unchanged),
        "unchanged_leaves": sum(pair.leaf_count for pair in diff.unchanged),
        "counts": counts,
        "changed_source_ids_a": len(diff.changed_source_ids_a),
        "changed_source_ids_b": len(diff.changed_source_ids_b),
        "entries": [
            {
                "status": entry.status,
                "kind": entry.kind,
                "path_a": list(entry.path_a) if entry.path_a is not None else None,
                "path_b": list(entry.path_b) if entry.path_b is not None else None,
                "hash_a": entry.hash_a,
                "hash_b": entry.hash_b,
                "origin_a": list(entry.origin_a) if entry.origin_a else None,
                "origin_b": list(entry.origin_b) if entry.origin_b else None,
                "leaves_a": len(entry.leaf_source_ids_a),
                "leaves_b": len(entry.leaf_source_ids_b),
            }
            for entry in diff.entries
        ],
        "entries_total": len(diff.entries),
    }
