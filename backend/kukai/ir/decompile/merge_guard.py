"""Страж между дельтой и документом — единственный провод `merge3` наружу.

`merge3.py` умеет трёхсторонний семантический merge: общий предок, две
разошедшиеся версии, типизованные конфликты вместо тихой перезаписи.  Чего
он НЕ умеет — назвать, ГДЕ в этом продукте берутся три версии одного
здания.  Ровно этого и не хватало: 420 строк и 20 тестов лежали на складе с
собственной пометкой докстринга «opt-in gate for future pipeline wiring».

Три версии берутся там, где у пересборки уже записана НАЗВАННАЯ ДЫРА.
Дельта-пересборка (волна 6, подключена 09.08.2026) сама говорит о себе:

    «дельта верна, только если в документе уже стоит здание базы; проверить
    это офлайн компилятор не может» — `precondition_ru`

Это не осторожность, это единственное место, где живая пересборка может
дать МОЛЧАЛИВО НЕВЕРНЫЙ исход: оператор прочитал здание (A), мы посчитали
дельту A→B, а оператор тем временем правил документ в Revit.  Дельта
построит ровно разницу A→B и промолчит о том, что под ней уже не A.  Правки
оператора при этом не «потеряются с ошибкой» — их просто никто не заметит.

Три версии, и все три — обычные разборы на диске:

* **предок O** — `base_doc_stamp`, разбор, от которого считали дельту;
* **наша сторона** — `current_doc_stamp`, СВЕЖИЙ разбор того же документа,
  то есть то, во что оператор его привёл;
* **их сторона** — `doc_stamp`, здание, которое мы собираемся построить.

ЧТО ЭТОТ СЛОЙ ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ.  Он СТРАЖ, а не материализатор.
Состояние `merge3` — мультимножество канонических опов, из него нельзя
построить программу: у канонического опа нет ни идентификаторов, ни ссылок,
и `leaves_to_program` его не примет.  Поэтому строится по-прежнему дельта
A→B, а merge отвечает ровно на один вопрос: БЕЗОПАСНО ЛИ её строить.  Врать
об этом нельзя — «мы сольём правки» звучало бы куда лучше, чем «мы откажем»,
и было бы неправдой.

Отсюда политика по умолчанию — `refuse`.  Конфликт это не предупреждение и
не совет: это две правки одного и того же, из которых наша сотрёт чужую.
Молча пережить такое имеет право только тот, кто явно сказал, что готов
(`allow_conflicts`), — и тогда конфликты всё равно едут в отчёт целиком.

И ГЛАВНОЕ, ЧТО ЭТОТ СЛОЙ ДАЁТ, когда конфликтов нет: `precondition_ru`
перестаёт быть обещанием.  Совпало состояние свежего разбора с состоянием
базы — условие ПРОВЕРЕНО, а не заявлено; разошлось без конфликтов — сказано,
на сколько именно и что дельта поверх этого встанет.
"""
from __future__ import annotations

from typing import Any

from kukai.ir.decompile.fold import TreeNode
from kukai.ir.decompile.merge3 import (
    POLICY_OURS,
    POLICY_REFUSE,
    Conflict,
    MergeError,
    merge3_trees,
)
from kukai.ir.decompile.rebuild import BuildingState

GUARD_SCHEMA = "kir-merge-guard/1"

#: Сколько конфликтов показать целиком.  ПОЛНОЕ число всегда рядом: обрезанный
#: список — это про длину отчёта, а обрезанное число было бы ложью о здании.
_SAMPLE_LIMIT = 20

#: Канонический оп — длинная строка; в образце она режется, и ровно поэтому
#: рядом с ней едет `truncated: true`, чтобы её не приняли за оп целиком.
_OP_CHARS = 160

VERDICT_CONFIRMED = "precondition_confirmed"
VERDICT_CLEAN = "diverged_clean"
VERDICT_CONFLICTING = "diverged_conflicting"

__all__ = [
    "GUARD_SCHEMA",
    "VERDICT_CLEAN",
    "VERDICT_CONFIRMED",
    "VERDICT_CONFLICTING",
    "guard_refusal",
    "guard_report",
]


def guard_refusal(exc: BaseException, **extra: Any) -> dict[str, Any]:
    """Отказ, который видно.  Никогда не притворяется «конфликтов нет»."""

    return {
        "schema": GUARD_SCHEMA,
        "ok": False,
        "error": {"type": type(exc).__name__, "message": str(exc)},
        **extra,
    }


def _sample(conflict: Conflict) -> dict[str, Any]:
    def _cut(value: str | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return {
            "op": value[:_OP_CHARS],
            "truncated": len(value) > _OP_CHARS,
        }

    return {
        "kind": conflict.kind,
        "source_id": conflict.source_id,
        "base_count": conflict.base_count,
        "current_count": conflict.ours_count,
        "target_count": conflict.theirs_count,
        "current": _cut(conflict.ours),
        "target": _cut(conflict.theirs),
    }


def guard_report(
    base_tree: TreeNode,
    current_tree: TreeNode,
    target_tree: TreeNode,
    *,
    base_label: str = "base",
    current_label: str = "current",
    target_label: str = "target",
) -> dict[str, Any]:
    """Безопасно ли строить дельту base→target в документ, который сейчас current.

    Конфликты считаются политикой `ours`, а НЕ `refuse`: под `refuse` слой
    поднимает исключение на первом же конфликте и списка не отдаёт, а страж
    обязан назвать ВСЕ.  Решение «отказать» принимает вызывающий по
    `verdict` — здесь только измерение.
    """

    try:
        base_state = BuildingState.of_tree(base_tree)
        current_state = BuildingState.of_tree(current_tree)
        result = merge3_trees(
            base_tree, current_tree, target_tree, policy=POLICY_OURS)
    except (MergeError, KeyError, TypeError, ValueError) as exc:
        return guard_refusal(
            exc, base=base_label, current=current_label, target=target_label)

    by_kind: dict[str, int] = {}
    for conflict in result.conflicts:
        by_kind[conflict.kind] = by_kind.get(conflict.kind, 0) + 1

    # Совпадение состояний — единственное честное «в документе стоит база».
    # Сравниваются мультимножества канонических опов, то есть наблюдаемое
    # здание, а не идентификаторы: перенумерованный документ обязан считаться
    # тем же, иначе страж кричал бы на каждый повторный разбор.
    identical = current_state == base_state
    if identical:
        verdict = VERDICT_CONFIRMED
    elif result.conflicts:
        verdict = VERDICT_CONFLICTING
    else:
        verdict = VERDICT_CLEAN

    return {
        "schema": GUARD_SCHEMA,
        "ok": True,
        "base": base_label,
        "current": current_label,
        "target": target_label,
        "verdict": verdict,
        "policy": POLICY_REFUSE,
        "identical_to_base": identical,
        "conflicts_total": len(result.conflicts),
        "conflicts_by_kind": dict(sorted(by_kind.items())),
        "auto_merged": result.auto_merged,
        "conflicts": [_sample(c) for c in result.conflicts[:_SAMPLE_LIMIT]],
        "conflicts_shown": min(len(result.conflicts), _SAMPLE_LIMIT),
        "message_ru": _message_ru(verdict, len(result.conflicts),
                                  result.auto_merged),
    }


def _message_ru(verdict: str, conflicts: int, auto_merged: int) -> str:
    if verdict == VERDICT_CONFIRMED:
        return ("свежий разбор документа совпал с базой — условие дельты "
                "ПРОВЕРЕНО, а не заявлено")
    if verdict == VERDICT_CLEAN:
        return (f"документ ушёл от базы на {auto_merged} правок, но ни одна "
                "не спорит с дельтой — дельта встанет поверх них")
    return (f"документ ушёл от базы, и {conflicts} правок спорят с дельтой: "
            "построить её значит стереть чужую работу молча")
