"""THE DEMAND FOR A SNAPSHOT MUST MATCH WHAT THE SNAPSHOT IS ACTUALLY READ FOR.

THE INCIDENT THAT BOUGHT THIS FILE (21.08.2026, an external audit).
`ground.py` holds ONE rule in TWO carriers:

    `_needs_pool`              — "will a snapshot be needed at all"
    the main resolve loop      — "should the pool be read for this parameter"

The first decides whether to REFUSE the `KIR-G103` program before any work at all; the second
decides what to do with a skipped parameter. Both enumerate the same
skips by hand, and nothing forces them to agree. By the time of the measurement
the mirror held THREE skips out of FIVE: `create_topography` and `place_family`
had been added to the resolve loop and not to `_needs_pool`.

THE COST, CAPTURED BY MEASUREMENT, not derived:

    create_topography variety=surface
      with an EMPTY snapshot (not a single pool) -> ok=True,  0 diagnostics
      WITHOUT a snapshot                          -> ok=False, KIR-G103

An empty snapshot compiles green — meaning the resolve loop reads NOT A SINGLE
pool. The refusal was demanding an artifact that, by construction, is never read.

WHY THIS TEST IS BUILT EXACTLY THIS WAY. Checking the list of skips by eye is
useless — it drifted apart right under someone's eyes. What is asked here is the CONSEQUENCE:
if a program compiles with an empty snapshot, it must also compile without
a snapshot, because an empty snapshot and its absence carry EXACTLY THE SAME
knowledge — not a single pool. This assertion is not about a list, and the list cannot be
rewritten in a way that makes the test go green dishonestly.

🔴 A BOUNDARY NAMED OUT LOUD: the converse is not true and is not checked here.
A program that was refused on an EMPTY snapshot (`KIR-G101`/`G102` — "pool is empty"),
says nothing about the demand for a snapshot: it read the snapshot just fine.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program

#: Programs whose resolve loop skips ALL groundable parameters.
#: Each one carries the reason the skip is legal, and that same reason stands
#: in `ground.py` next to the skip itself.
#:
#: 🔴 THE LIST IS CLOSED AND NOT COMPLETE. It cannot be complete by construction:
#: there is nothing to assemble a valid program with for every op in the registry, and an empty
#: cell here means "nobody guards this branch", not "it has no
#: skips". When you add a new skip to `ground.py`, add a line here too.
NO_POOL_PROGRAMS: tuple[tuple[str, dict, str], ...] = (
    (
        "create_topography variety=surface",
        {"ops": [{
            "op": "create_topography", "id": "T1", "variety": "surface",
            "points_mm": [[0, 0, 0], [5000, 0, 0], [5000, 5000, 200],
                          [0, 5000, 0]],
        }]},
        "у ПОВЕРХНОСТИ рельефа в API нет ни уровня, ни типа — отметка живёт "
        "в Z каждой точки; оба грунтуемых параметра опа нерелевантны",
    ),
    # 🔴 ADDED 26.08.2026, AND HERE IS WHAT BOUGHT IT. The list stood at ONE line,
    # even though its own header instructs adding to it with every new skip.
    # This was found while looking into the red `test_no_snapshot_is_typed_refusal`
    # (`b3d37271`): that red was nearly removed outright, and it was guarding `KIR-G103`
    # for `create_wall_foundation`. A guard whose corpus is a single example
    # checks the law on one branch and stays silent about the rest.
    #
    # Both entries are MEASURED, not derived: both inputs compile green both with
    # an empty snapshot and without one — that is, the law holds for them and will be
    # caught if it stops holding.
    (
        "create_wall тип ОПУЩЕН, level адресован id",
        {"ops": [{
            "op": "create_wall", "id": "W1",
            "p0_mm": [0, 0], "p1_mm": [5000, 0],
            "level": {"by": "element_id", "value": 700}, "height_mm": 3000,
        }]},
        "тип опущен -> документный тип по умолчанию (`OPS_WITH_DOC_DEFAULT_TYPE`), "
        "пул не читается; level адресован id, пул не нужен и ему",
    ),
    (
        "create_wall_foundation тип ОПУЩЕН",
        {"ops": [{
            "op": "create_wall_foundation", "id": "WF1",
            "wall": {"by": "element_id", "value": 900},
        }]},
        "тот же документный тип по умолчанию; носитель адресован id. Именно "
        "эту ветку 24.08 чинили через `OPS_WITH_DOC_DEFAULT_TYPE`, и до сих "
        "пор она в этом стороже не стояла",
    ),
)

#: 🔴 WHAT IS MISSING HERE, AND THIS IS MY OWN BLINDNESS, NOT THEIR UNFITNESS. I tried adding
#: `create_floor` and `create_filled_region` with the type omitted — both programs
#: refused with `KIR-P003` for me (unknown envelope field), meaning I failed to
#: assemble them validly, not that they demanded a snapshot. Recorded separately so that
#: the next reader does not mistake an empty cell for a measured negative
#: answer: "did not check" and "checked, and it does not fit" are different assertions.


class TheSnapshotDemandMatchesTheSnapshotUse(unittest.TestCase):
    """A snapshot may be demanded exactly where it is read."""

    def test_a_program_green_on_an_empty_snapshot_is_green_without_one(self):
        for name, program, why in NO_POOL_PROGRAMS:
            with self.subTest(name):
                # Arm A: an empty snapshot. There are no pools at all; if the resolver
                # touches even one, there will be a refusal here, and the case is invalid.
                empty = compile_program(program, revit_version="2023",
                                        snapshot={"pools": {}})
                self.assertTrue(
                    empty.ok,
                    f"{name}: случай негоден — на ПУСТОМ снимке уже отказ "
                    f"{[d.code for d in (empty.diagnostics or [])]}, "
                    f"значит какой-то пул всё-таки читается ({why})")

                # Arm B: there is no snapshot. The knowledge is the same — not a single pool.
                none = compile_program(program, revit_version="2023",
                                       snapshot=None)
                codes = [d.code for d in (none.diagnostics or [])]
                self.assertNotIn(
                    "KIR-G103", codes,
                    f"{name}: снимок ТРЕБУЕТСЯ и не ЧИТАЕТСЯ. Пустой снимок "
                    f"собрался зелёным, то есть ни один пул не нужен — "
                    f"{why}. Спрос на снимок разошёлся с его использованием: "
                    f"пропуск заведён в цикле резолва `ground.py` и не "
                    f"заведён в `_needs_pool`.")
                self.assertTrue(none.ok, f"{name}: {codes}")

    def test_the_two_mirrors_ask_one_predicate(self):
        """Both carriers must query ONE function, not their own list.

        The control is structural and deliberately coarse: it does not parse the logic, it
        demands that the predicate exist and be called from both places. As long as
        each carrier enumerates the skips on its own, they will drift apart —
        and that is exactly what happened.
        """
        import inspect

        from kir import ground

        src = inspect.getsource(ground)
        self.assertIn(
            "def _omitted_param_is_irrelevant", src,
            "нет общего предиката: пропуски перечислены дважды руками")
        self.assertGreaterEqual(
            src.count("_omitted_param_is_irrelevant("), 3,
            "предикат объявлен, но зовётся не из обоих носителей — "
            "объявление плюс два вызова это минимум три упоминания")


if __name__ == "__main__":
    unittest.main()
