"""The hosted index reaches all the way to the move PROPOSAL, not just to the verdict.

🔴 WHAT PAID FOR THIS FILE, BY THE MEASUREMENT OF 25.08.2026.

`judge` accepts `hosted` and uses it to compute `host_state` — "the host is
declared and it is the same element" versus "declared and a DIFFERENT one".
The second pass, `_upgrade_moves`, is declared WITHOUT this parameter, and
its internal call to `resolve.propose` passes only `hood`, `pair_kind`,
`finding_id`.

    judge           hosted: PRESENT
    _upgrade_moves  hosted: ABSENT
    propose(...)    hood, pair_kind, finding_id   — hosted not passed

`propose` reads it (six times in its body) and, without it, never sees
`contradicts`, so it always falls through to the tabular recommendation.

THE COST, MEASURED ON THE TREE. Header of `resolve.py:138-149`: the
label-based guess strips 497 pairs, of which 239 — **48.1%** — are
`contradicts`, i.e. "the host is declared and it is a different element". A
door overlapping a wall it does not live in gets the verb «узел;
геометрически развело бы» (joint; would have geometrically resolved)
instead of «сдвиньте» (move it) — even though, in the SAME row, `Judged`'s
`host_state` field, computed by `judge`, reads `contradicts`. Two carriers
of the same fact diverge silently within one receipt.

BOUNDARY. What is judged here is the WIRE: that the index gets through.
That 239 pairs will change their recommendation as a result follows from
`_recommendation`, but is not measured here by a live run on a real batch.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import unittest

from kir import clash_judgement as cj


class ИндексХозяевДоезжаетДоПредложения(unittest.TestCase):

    def test_второй_проход_принимает_индекс(self):
        параметры = inspect.signature(cj._upgrade_moves).parameters
        self.assertIn(
            "hosted", параметры,
            "второй проход не знает об индексе хозяев — предложение хода "
            "выносится вслепую к тому, что вердикт уже посчитал")

    @staticmethod
    def _именованные(функция, имя_вызова: str) -> set[str] | None:
        """Names of the call's keyword arguments — via PARSING, not a substring.

        🔴 The first edition searched with the `_upgrade_moves\\(([^)]*)\\)`
        regex, and `[^)]*` stopped at the very first inner parenthesis
        (`float(propose_budget_ms)`). The test never saw the argument that
        came AFTER it and declared it missing — i.e. it turned red on a
        correct fix.
        """
        дерево = ast.parse(textwrap.dedent(inspect.getsource(функция)))
        for узел in ast.walk(дерево):
            if not isinstance(узел, ast.Call):
                continue
            цель = узел.func
            имя = (цель.attr if isinstance(цель, ast.Attribute)
                   else getattr(цель, "id", None))
            if имя == имя_вызова:
                return {kw.arg for kw in узел.keywords if kw.arg}
        return None

    def test_вызов_propose_передаёт_индекс(self):
        имена = self._именованные(cj._upgrade_moves, "propose")
        self.assertIsNotNone(имена, "вызов propose исчез — стенд смотрит не туда")
        self.assertIn("hosted", имена,
                      f"propose зовётся без индекса: {sorted(имена)}")

    def test_judge_передаёт_индекс_во_второй_проход(self):
        имена = self._именованные(cj.judge, "_upgrade_moves")
        self.assertIsNotNone(имена, "вызов _upgrade_moves исчез")
        self.assertIn("hosted", имена,
                      "вердикт знает индекс и не отдаёт его второму проходу")

    def test_КОНТРОЛЬ_propose_по_прежнему_умеет_без_индекса(self):
        """The `None` default must remain: `propose` has callers that have no
        index, and there is no reason to change behavior for them."""
        from kir.clash import resolve as rs
        параметр = inspect.signature(rs.propose).parameters["hosted"]
        self.assertIs(параметр.default, None)
