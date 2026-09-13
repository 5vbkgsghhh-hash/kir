"""WHO YIELDS TO WHOM, AS CODE — because three callers ask and prose drifts.

Seniority is asked by THREE: merge (`modify_modify` on one address), clash
(two bodies in one place), and norms (a rule one of two must break). Three
copies of a table diverge on the first new section, and that is this tree's
named defect: two places holding one decision (the KIR-mode boundary lived in
the palette and the dispatcher, and they диverged — audit H §1.5).

🔴 ONE LINE IS NOT NEGOTIABLE. `ORDER[0] == "КР"` and КР ahead of АР is the
OWNER's word ("КР важнее АР всегда"), not a preference of this module. The pin
holds it so a future wave cannot quietly re-sort it.

🔴 THE REST IS A PROPOSAL WITH REASONS, AND THE OWNER EDITS IT. Every position
below carries its cause in `REASON`, in one Russian line, because the same
line goes into the journal and to the expert — a decision an expert cannot
read is a decision it will argue with.

🔴 THE LEAD DECIDES, NOT THE HUMAN — except twice. `human_needed` is True in
exactly two cases (the owner's word): the brief admits two lawful readings,
and the decision changes what was explicitly asked. Everywhere else asking a
human is palka (h) of `HARNESS_VERDICT`: "UI объясняет словами то, что должен
делать агент".
"""
from __future__ import annotations

from typing import Any

__all__ = ["ORDER", "REASON", "SECTIONS", "decide", "rank", "yields_to"]

#: Order of stubbornness: the earlier, the less it yields. КР and АР are the
#: owner's; the rest is H's proposal (`EXPERT_TURN_CONTRACT_RU.md` §3.2).
ORDER: tuple[str, ...] = (
    "КР",
    "АР",
    "ВК-самотёк",
    "ОВ",
    "ВК-напор",
    "ЭОМ",
    "СС",
    "ГП",
)

#: Why each stands where it stands. One line, Russian, because this line IS
#: the journal entry and the expert's explanation — not a comment about them.
REASON: dict[str, str] = {
    "КР": "несущее: перенос колонны — пересчёт, а не правка",
    "АР": "задаёт назначение и габариты, в которых живут остальные",
    "ВК-самотёк": "уклон не переносится: сдвиг лотка — переделка всей ветки",
    "ОВ": "крупное сечение, но отвод дешевле уклона",
    "ВК-напор": "насос допускает обход",
    "ЭОМ": "лоток и кабель изгибаются дешевле всего из инженерных",
    "СС": "наименьшее сечение, наибольшая свобода маршрута",
    "ГП": "внутри контура здания всегда уступает КР",
}

#: What an agent actually types (the door's `assign` enum). `ВК` arrives
#: unqualified and has TWO ranks in `ORDER`; `_resolve` decides which.
SECTIONS: tuple[str, ...] = ("АР", "КР", "ОВ", "ВК", "ЭОМ")


def _resolve(section: str) -> str:
    """An unqualified `ВК` counts as GRAVITY, and the asymmetry is the reason.

    🔴 DOUBT LEANS TOWARD THE STRONGER, not the weaker. If we read a plain
    `ВК` as pressure and it was gravity, we have asked gravity to change its
    slope — a redesign of the whole branch. If we read it as gravity and it
    was pressure, we moved a duct that need not have moved. The two errors are
    not the same size, so the default is not the middle. Same shape of
    argument as `serving._plan_writes`.
    """
    name = (section or "").strip()
    if name == "ВК":
        return "ВК-самотёк"
    return name


def rank(section: str) -> int:
    """Position in `ORDER`. An unknown section is LAST, not an exception:
    a raise here would take down a merge over a name nobody declared."""
    resolved = _resolve(section)
    if resolved in ORDER:
        return ORDER.index(resolved)
    return len(ORDER)


def yields_to(loser: str, winner: str) -> bool:
    """Whether `loser` gives way to `winner`. Equal ranks yield to nobody."""
    return rank(loser) > rank(winner)


def decide(conflict: Any, sections: tuple[str, str]) -> dict:
    """One decision, one line, and the line goes to two places at once.

    `conflict` is what the merge or the clash handed over: at minimum
    `{"kind": …, "path": …}` — the address form `project_merge` already
    produces (`{"kind":"modify_modify","path":"instances/tower-b"}`). Two
    optional flags are the ONLY way `human_needed` becomes True:

      * `brief_ambiguous` — the brief admits two lawful readings. Measured
        offline: «стена 6000 мм» read as length where height was equally
        legal; the agent guessed and was right BY LUCK (audit H §2.5в).
      * `changes_explicit_request` — seniority removes something the human
        asked for by name ("сарай с окном", and КР takes the window out).

    Returns the decision AND `line_ru` — the single string for the journal
    (`kir/bureau/`, the same `checkpoint` events that carry budget and Stop)
    and for the expert's `decision` field. One string, not two: two would
    drift, and the expert would be told a reason the journal does not hold.
    """
    first, second = sections
    if yields_to(second, first):
        winner, loser = first, second
    elif yields_to(first, second):
        winner, loser = second, first
    else:
        # Equal rank — including two unknown sections. Nobody yields, and
        # the door says so instead of inventing a winner.
        return {
            "winner": None, "loser": None,
            "rule": "равный ранг",
            "reason": "разделы равны по старшинству — уступать некому",
            "human_needed": True,
            "line_ru": (f"{first} и {second} равны по старшинству: "
                        f"{_where(conflict)} решает человек"),
        }

    resolved = _resolve(winner)
    rule = f"{_resolve(loser)} уступает {resolved}"
    reason = REASON.get(resolved, "порядок разделов")
    human = bool(_flag(conflict, "brief_ambiguous")) or bool(
        _flag(conflict, "changes_explicit_request"))
    line = f"{rule}: {reason}. Спор: {_where(conflict)}."
    if _flag(conflict, "brief_ambiguous"):
        line += " Бриф читается двумя способами — спрашиваю человека."
    elif _flag(conflict, "changes_explicit_request"):
        line += " Решение меняет явно просимое — спрашиваю человека."
    return {"winner": winner, "loser": loser, "rule": rule, "reason": reason,
            "human_needed": human, "line_ru": line}


def _flag(conflict: Any, name: str) -> bool:
    if isinstance(conflict, dict):
        return bool(conflict.get(name))
    return bool(getattr(conflict, name, False))


def _where(conflict: Any) -> str:
    """The address, in words. A conflict without an address is named as such:
    «не назван» is information, an empty string is not."""
    get = (conflict.get if isinstance(conflict, dict)
           else lambda k, d=None: getattr(conflict, k, d))
    kind = get("kind") or "конфликт"
    path = get("path") or get("address") or "адрес не назван"
    return f"{kind} по адресу {path}"
