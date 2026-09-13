"""THE BUILDING AS SHAPE, NOT AS A LIST OF OPERATIONS: O(changes) instead of O(operations).

🔴 WHY, IN ONE NUMBER. The 21.08 repeat-folding gave −58% and RAN OUT: what remains in the
receipt is real coordinates and real ids, and there is nothing left to compress there.
Growth is ~200 bytes per element, i.e. 20,000 operations ≈ 4 MB. From here on, what shrinks
this further is not compression, but A DIFFERENT DATA MODEL.

At a stage boundary, the author looks not at operations, but at **what happened to the
building**. This question has a size of O(floors × categories), not O(elements), and does not
grow with the model: a building with 34,000 elements has a couple dozen floors, and about fifty
categories.

WHAT THIS MODULE DOES NOT DO, AND THIS IS THE MAIN LIMITATION. The shape does NOT REPLACE
the per-element receipt and does not claim its role. It answers the question
"what changed", not "what exactly was built": it cannot be used to find a specific
wall, cannot reconstruct the program, and cannot judge what was built. Reading it
instead of the receipt would mean getting a pretty summary instead of proof —
exactly the substitution this entire compiler was written against. Therefore:

    the receipt      PROVES   every element, expensive, O(operations)
    the stage shape   SHOWS    what happened to the building, cheap, O(changes)

🔴 AN EMPTY CELL AND A ZERO CELL ARE DIFFERENT FACTS. A category that was NOT on the floor
and still isn't does not enter the delta at all. A category that WAS there and
disappeared enters with a minus sign. Collapsing them both to "zero" would mean hiding
a deletion — the most expensive change there is.

🔴 AND A SECOND BLIND SPOT, NAMED HERE RATHER THAN DISCOVERED LATER. An edit IN
PLACE — a type change, a shift, a rotation — does not change the element count, and in the
delta it is NOT VISIBLE. That is why "the building did not change" is printed together with
this caveat, never alone: without it, the summary would claim that no work
was done exactly when all the work happened.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

__all__ = ("Cell", "BuildingShape", "shape_of", "shape_delta",
           "delta_note_ru", "NO_LEVEL")

#: The marker assigned to an element without a level. NOT an empty string: "the level is
#: unnamed" is a fact about the model, and it must be visible in the summary, not merged
#: with whichever floor comes first.
NO_LEVEL = "(уровень не назван)"


@dataclass(frozen=True, slots=True)
class Cell:
    """One cell of the summary: how many, and at what dimensions."""

    count: int
    #: The cell's dimension in mm; `None` — none of the elements had a dimension.
    bbox_mm: tuple[float, float, float, float, float, float] | None = None

    def merged(self, other: "Cell") -> "Cell":
        if self.bbox_mm is None:
            box = other.bbox_mm
        elif other.bbox_mm is None:
            box = self.bbox_mm
        else:
            a, b = self.bbox_mm, other.bbox_mm
            box = (min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]),
                   max(a[3], b[3]), max(a[4], b[4]), max(a[5], b[5]))
        return Cell(self.count + other.count, box)


@dataclass(frozen=True, slots=True)
class BuildingShape:
    """The building folded down to (floor × category). The size does NOT depend on the model."""

    cells: dict[tuple[str, str], Cell] = field(default_factory=dict)
    #: How many elements went into the shape. Kept separate so that "a summary over
    #: zero elements" and "a summary that was never built" are distinguishable.
    seen: int = 0

    @property
    def levels(self) -> tuple[str, ...]:
        return tuple(sorted({lvl for lvl, _ in self.cells}))

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({cat for _, cat in self.cells}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "kir-stage-shape/1",
            "seen": self.seen,
            "levels": len(self.levels),
            "categories": len(self.categories),
            "cells": {
                f"{lvl} · {cat}": {
                    "n": cell.count,
                    "bbox_mm": list(cell.bbox_mm) if cell.bbox_mm else None,
                }
                for (lvl, cat), cell in sorted(self.cells.items())
            },
        }


def _bbox_of(row: Mapping[str, Any]):
    lo, hi = row.get("bbox_min_mm"), row.get("bbox_max_mm")
    if not (isinstance(lo, (list, tuple)) and isinstance(hi, (list, tuple))):
        return None
    if len(lo) != 3 or len(hi) != 3:
        return None
    try:
        return (float(lo[0]), float(lo[1]), float(lo[2]),
                float(hi[0]), float(hi[1]), float(hi[2]))
    except (TypeError, ValueError):
        return None


def shape_of(rows: Iterable[Mapping[str, Any]]) -> BuildingShape:
    """Elements -> shape. One pass, memory O(floors x categories)."""
    cells: dict[tuple[str, str], Cell] = {}
    seen = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        seen += 1
        level = str(row.get("level_name") or row.get("level") or "") or NO_LEVEL
        category = str(row.get("category") or "?")
        key = (level, category)
        cell = Cell(1, _bbox_of(row))
        cells[key] = cells[key].merged(cell) if key in cells else cell
    return BuildingShape(cells=cells, seen=seen)


def shape_delta(before: BuildingShape | None,
                after: BuildingShape) -> dict[str, Any]:
    """What changed. The size is O(CHANGES), not O(cells).

    `before is None` — the first stage: EVERYTHING counts as a change, and this
    is stated in words, rather than left for the reader to infer from the delta being large.
    """
    prev = before.cells if before is not None else {}
    # 🔴 THERE IS ONE UNIVERSE OF COMPARISON, AND IT IS NAMED (F-366, 29.08.2026).
    # The numerator was computed over the UNION of "before" and "after", while the
    # denominator (`cells_total`) was taken only from "after" — a cell that disappeared
    # entirely was included in the numerator and NOT included in the denominator.
    #
    # The visible consequence: a stage that tore down the only row of walls printed
    # «ИЗМЕНИЛОСЬ клеток: 1 из 0» — plausible-looking and mathematically
    # impossible. Worse, SILENT: a building that lost one category out of two
    # printed «1 из 1» and read as "everything that existed changed", even though
    # TWO cells were being compared. No reader will ever catch the second one, and it is
    # exactly that — the real defect; the first merely makes it visible at the edge.
    universe = set(prev) | set(after.cells)
    changed: dict[str, dict[str, Any]] = {}
    for key in universe:
        was = prev.get(key)
        now = after.cells.get(key)
        n_was = was.count if was else 0
        n_now = now.count if now else 0
        if n_was == n_now:
            continue
        changed[f"{key[0]} · {key[1]}"] = {
            "level": key[0], "category": key[1],
            "was": n_was, "now": n_now, "delta": n_now - n_was,
        }
    added = sum(c["delta"] for c in changed.values() if c["delta"] > 0)
    removed = -sum(c["delta"] for c in changed.values() if c["delta"] < 0)
    return {
        "schema": "kir-stage-delta/1",
        "first_stage": before is None,
        "cells_changed": len(changed),
        # THE DENOMINATOR OF THE SAME FRACTION as the numerator: how many cells were
        # COMPARED AT ALL. The only consumer of this key is the "changed out of
        # total" fraction in `delta_note_ru`, and for that, this is exactly the right universe.
        "cells_total": len(universe),
        # The value that `cells_total` used to carry is NOT LOST — it is
        # now named by its own name. Keys are only added: the core fix
        # adds, it does not rename.
        "cells_now": len(after.cells),
        "elements_added": added,
        "elements_removed": removed,
        "changed": changed,
    }


def delta_note_ru(delta: Mapping[str, Any], *, top: int = 6) -> str:
    """The delta as one line. Truncation NAMES itself and names the remainder."""
    blind = ("Правка НА МЕСТЕ — смена типа, сдвиг, поворот — числа не меняет "
             "и здесь НЕ ВИДНА")
    if delta.get("first_stage"):
        head = (f"ПЕРВАЯ СТАДИЯ: сравнивать не с чем, изменением считается "
                f"всё — {delta.get('elements_added', 0)} элементов в "
                f"{delta.get('cells_changed', 0)} клетках")
    elif not delta.get("cells_changed"):
        return (f"ЗДАНИЕ НЕ ИЗМЕНИЛОСЬ В ЧИСЛАХ: ни в одной из "
                f"{delta.get('cells_total', 0)} клеток (этаж x категория) "
                f"количество не сдвинулось. {blind}")
    else:
        head = (f"ИЗМЕНИЛОСЬ клеток: {delta['cells_changed']} из "
                f"{delta['cells_total']}; +{delta.get('elements_added', 0)} / "
                f"−{delta.get('elements_removed', 0)} элементов")
    rows = sorted(delta.get("changed", {}).values(),
                  key=lambda c: -abs(c["delta"]))
    shown = rows[:top]
    body = "; ".join(f"{c['level']} · {c['category']} "
                     f"{c['was']}→{c['now']}" for c in shown)
    tail = ""
    if len(rows) > top:
        tail = (f"; ещё {len(rows) - top} клеток не показаны "
                f"(показаны {top} самых крупных по модулю изменения)")
    return f"{head}. {body}{tail}. {blind}"
