"""A PROVEN EFFECT IS NOT REWRITTEN INTO «ЭФФЕКТА НЕ БЫЛО».

🔴 WHY (24.08.2026). TWO audit findings, both reproduced by production
functions on one journal slot, both about ONE root cause:
`_TURN_JOURNAL_SLOT` is SHARED, and a late refusal was moving SOMEONE
ELSE'S already-committed record.

    CHUNKS (serving.py:4070)
        chunk 1 committed -> `committed`
        chunk 2 refused BEFORE the effect (compilation / ground / gate)
        -> the program's shared record moves into `refused_pre_effect`
        -> `built()` loses walls THAT ARE STANDING IN THE MODEL

    PHASES (serving.py:3565)
        phase k did not link by reference across the boundary — its body
        WAS NEVER INVOKED, the slot still points at phase k-1's record in
        `committed`
        -> it is converted to a terminal refusal

The receipt for that same move, meanwhile, was shouting the opposite:
«чанки 1..k УЖЕ В МОДЕЛИ и НЕ ОТКАЧЕНЫ», «ПОВТОРЯТЬ ПЛАН ЦЕЛИКОМ НЕЛЬЗЯ».
**Two carriers of the fact "what stands in the model" contradicted each
other**, and the journal's reader — the building judge, the clash bundle,
the viewer's `base_digest` — believed the wrong one. The model, having
asked "what stands", got back "nothing" and built a SECOND TIME.

The law was stated in `serving.py` verbatim — «позднейшая ошибка может
ослабить ДОКАЗАТЕЛЬСТВО, но не имеет права переписать ИЗВЕСТНЫЙ эффект в
неподтверждённый» — and applied ONLY within a single call. The journal did
not know it.

The stage name names the fact: `refused_pre_effect` — «отказано ДО
эффекта». Coming from `committed`, this is a LIE, not a loss of precision.
"""
from __future__ import annotations

import unittest

from kir.live import journal as J

ПРОГРАММА = {"ir_version": "1.0",
             "ops": [{"op": "create_wall", "id": "W1"}]}


class ЗакоммиченноеНеУходитВБоковую(unittest.TestCase):

    def setUp(self):
        self.ключ = J.key_for("тест-эффект-монотонен", "док")
        J.reset(self.ключ)
        self.rec = J.append(self.ключ, ПРОГРАММА, plan_digest="d")
        for стадия in ("grounded", "dispatched", "committed"):
            self.assertTrue(J.advance(self.ключ, self.rec.seq, стадия), стадия)

    def tearDown(self):
        J.reset(self.ключ)

    def _построено(self):
        ж = J.get(self.ключ)
        return [r.seq for r in ж.records if r.stage in J.BUILT_STAGES]

    def test_КОНТРОЛЬ_PASS_после_коммита_запись_ПОСТРОЕНА(self):
        """Without it, the red below would mean nothing."""
        self.assertEqual(self._построено(), [self.rec.seq])

    def test_ни_одна_боковая_стадия_не_принимается(self):
        """🔴 RED before the fix on ALL THREE: they all assert the absence
        of a proven effect, and each one moving from `committed` is a
        lie."""
        for боковая in ("refused_pre_effect", "rolled_back",
                        "running_unknown"):
            with self.subTest(боковая=боковая):
                self.assertIsNone(
                    J.get(self.ключ).advance(self.rec.seq, боковая),
                    f"{боковая} стёрла бы построенное здание")

    def test_построенное_переживает_поздний_отказ(self):
        """The chunk scenario, verbatim: a commit, then a refusal BEFORE
        the effect."""
        J.advance(self.ключ, self.rec.seq, "refused_pre_effect")
        self.assertEqual(self._построено(), [self.rec.seq])

    def test_вперёд_по_главной_линии_по_прежнему_можно(self):
        """CONTROL: the fix has no right to freeze the record entirely."""
        self.assertTrue(J.advance(self.ключ, self.rec.seq, "accepted"))
        self.assertEqual(self._построено(), [self.rec.seq])


class ДоКоммитаБоковаяПоПрежнемуЗАКОННА(unittest.TestCase):
    """🔴 FAIL CONTROL for the entire fix.

    A refusal BEFORE the effect is a normal and frequent occurrence: the
    compiler, ground, a gate. Forbidding it would mean breaking the honest
    path for the sake of the dishonest one.
    """

    def test_из_grounded_в_отказ_можно(self):
        ключ = J.key_for("тест-отказ-до-эффекта", "док")
        J.reset(ключ)
        try:
            rec = J.append(ключ, ПРОГРАММА, plan_digest="d2")
            J.advance(ключ, rec.seq, "grounded")
            self.assertTrue(J.advance(ключ, rec.seq, "refused_pre_effect"))
            стадии = [r.stage for r in J.get(ключ).records]
            self.assertEqual(стадии, ["refused_pre_effect"])
        finally:
            J.reset(ключ)

    def test_из_dispatched_в_неизвестность_можно(self):
        """«Отправлено, ответа нет» is a legitimate and NECESSARY side
        stage."""
        ключ = J.key_for("тест-неизвестность", "док")
        J.reset(ключ)
        try:
            rec = J.append(ключ, ПРОГРАММА, plan_digest="d3")
            J.advance(ключ, rec.seq, "grounded")
            J.advance(ключ, rec.seq, "dispatched")
            self.assertTrue(J.advance(ключ, rec.seq, "running_unknown"))
        finally:
            J.reset(ключ)


if __name__ == "__main__":
    unittest.main()


class УдержаниеВКИР_НЕ_ЕСТЬ_ОТКАЗ(unittest.TestCase):
    """🔴 A third finding of the same kind (serving.py:4393), 24.08.2026.

    The product mode «строим в КИР, а не в Ревите» honestly returns
    `program_not_started()` — execution genuinely never happened. But the
    stage map converts `not_started` into `refused_pre_effect`, and that is
    a SIDE AND TERMINAL stage. A design published as `planned` and WAITING
    for the "move to Revit" button disappeared from `standing()` and could
    NEVER be moved — pressing the button had no chance of being reflected
    in the journal.

    The batch judge, in that same move, printed `dropped_from_pack: 1` with
    the caption «отказ до записи либо откат» about a program that no one
    had refused.
    """

    def test_удержанная_программа_НЕ_двигает_журнал(self):
        from unittest import mock
        from kir import serving as S
        from kir.outcome import program_not_started
        тронуто: list = []
        with mock.patch.object(S, "_stage_the_journal",
                               side_effect=тронуто.append):
            S._with_outcome({"ok": True, "held_in_kir": True},
                            program_not_started())
        self.assertEqual(тронуто, [],
                         "удержание оставляет запись на `planned` — она там "
                         "уже стоит с публикации")

    def test_КОНТРОЛЬ_обычный_исход_журнал_ДВИГАЕТ(self):
        """Without it, the fix could disable the journal entirely."""
        from unittest import mock
        from kir import serving as S
        from kir.outcome import program_not_started
        тронуто: list = []
        with mock.patch.object(S, "_stage_the_journal",
                               side_effect=тронуто.append):
            S._with_outcome({"ok": False}, program_not_started())
        self.assertEqual(len(тронуто), 1)

    def test_исключение_названо_ОДНИМ_признаком_результата(self):
        """The funnel remains the ONLY one: a second key is a second
        carrier."""
        import inspect
        from kir import serving as S
        src = inspect.getsource(S._with_outcome)
        self.assertEqual(src.count("_stage_the_journal("), 1)
        self.assertIn('result.get("held_in_kir")', src)
