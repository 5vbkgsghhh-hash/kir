"""Семейство, которое Revit флипать не даёт, не должно убивать программу.

ОТКУДА ПРАВИЛО — ЖИВОЙ КОРПУС. `data/telemetry/kir_witness.jsonl`, все 16
красных строк `create_door` (21.07, Revit 2026): 4 — `KIR-X004` (нарушенные
постусловия), 12 — `KIR-X003` (рантайм-отказы, причина в корпусе НЕ записана:
ни одна строка из 1306 не несёт поля с текстом отказа). Три различных
нарушения, дословно:

    2026-07-21T16:26:28  KIR-X004  committed=false
        ["PD: hand flip state mismatch (semantic)",
         "PD: facing flip state mismatch (semantic)"]
    2026-07-21T16:05:06  KIR-X004  committed=false
        ["PD: mirrored state mismatch (semantic)",
         "PD: facing flip state mismatch (semantic)"]
    2026-07-21T12:40:36  KIR-X004  committed=false
        ["PD: mirrored state mismatch (semantic)"]

Во всех трёх `geometry_ok=true` и `topology_ok=true`: дверь встала в нужную
стену, в нужную точку, на нужной отметке. Не сошлась ОДНА створка — и вся
программа откатилась (`committed=false`).

ЦЕНУ НАЗЫВАЕМ ЗАМЕРЕННУЮ, А НЕ КРАСИВУЮ. Все 16 красных строк — программы из
ДВУХ опов (`create_wall`+`create_door`), значит по корпусу потеряна одна
правильная стена на дверь. Важно не это число, а МАСШТАБ механизма: вердикт
свидетеля программный по построению, поэтому на перестройке тот же дефект
стоит целого чанка материализатора (`MAX_BULK_OPS = 300`), а отказ под
`per_op` стоит ровно своего опа.

ЧЕЙ ЭТО ФАКТ. Не «молча вставленный default»: `tests/test_silent_defaults.py`
замерил 31.07, что флипы в нормализованный оп при молчании вызывающего НЕ
попадают (шесть молчаливых defaults, флипов среди них нет). Значит вызывающий
флипы НАЗВАЛ, а `CanFlipHand`/`CanFlipFacing=false` — факт о СЕМЕЙСТВЕ:
Revit отказывается менять навеску этого типа. Пост-фактум сделать с ним
нечего: единственный обходной путь — `MirrorElements(mirrorCopies=true)` —
запрещён навсегда живым замером 27.07 (SOB6.2), где зеркало на hosted-двери
уносило геометрию ЧУЖИХ дверей на другом хосте в точку [0,0], и per-op
SubTransaction этого не удерживал (`8a8c3038`).

ЧТО БЫЛО НЕ ТАК. Факт о семействе выражался НАРУШЕННЫМ ПОСТУСЛОВИЕМ, а оно
программного масштаба: вердикт свидетеля валит всю транзакцию, сколько бы
опов в ней ни было. При этом у `place_family` в том же файле ровно на этот
случай стоит ОТКАЗ, а не постусловие — то есть компилятор вёл себя двумя
разными способами в одной ситуации, и hosted была та сторона, где платила
вся программа.

ЧТО ДОЛЖНО БЫТЬ. Типизированный отказ, который НАЗЫВАЕТ семейство и СЛЕДУЮЩИЙ
ХОД (взять другой тип). Под `per_op` он уносит только свой оп — соседи
остаются закоммиченными; под `atomic` (одноопная программа) откат честен и
неизбежен, но у него теперь названа причина. Закон «никаких зеркал на hosted»
при этом не ослабляется ни на байт: отказ — это ОТСУТСТВИЕ действия, а не
новое действие.

ЗЕРКАЛО — УЖЕ ЗАКРЫТО НЕ ЗДЕСЬ, И ЭТО ВАЖНО НЕ ЧИНИТЬ ДВАЖДЫ. У
hosted-экземпляра рычага для `Mirrored` нет вообще: с F5 v4 эмиттер зеркала не
ставит (`mirror = ""`), а `Mirrored` — признак ПРОИЗВОДНЫЙ (= Hand XOR Facing,
живые пробы P2/P3/P6 21.07). Пять из десяти нарушений этого куста в корпусе —
именно `mirrored` (три из них у `place_family`). Все они снимаются РАНЬШЕ
эмиссии: `authoring_validation` отказывает противоречивой тройке на разборе
(`KIR-T002`, «mirrored — производное состояние»), и этот отказ уже стоял в
дереве. Здесь он только закреплён тестом — менялись лишь ветки
`hand`/`facing`.
"""
from __future__ import annotations

import copy
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_fw_queue.jsonl"))

from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


def _door(**extra):
    op = {"op": "create_door", "id": "PD",
          "host": {"by": "ref", "value": "W1"}, "offset_mm": 1000}
    op.update(extra)
    return op


def _prog(*ops):
    return {"ir_version": "1.0", "intent": "двери",
            "ops": [{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                     "p1_mm": [6000, 0],
                     "level": {"by": "element_id", "value": 42}},
                    *ops]}


def _compile(*ops, isolation: str = "atomic"):
    return compile_program(copy.deepcopy(_prog(*ops)), revit_version="2023",
                           snapshot=GROUND_SNAPSHOT, bulk=True,
                           isolation=isolation)


def _cs(*ops, isolation: str = "atomic") -> str:
    out = _compile(*ops, isolation=isolation)
    assert out.ok, [d.as_dict() for d in out.diagnostics]
    return out.csharp


class AFamilyThatCannotFlipMustRefuseItsOwnOp(unittest.TestCase):
    """Опровергающий тест строк 16:26:28 и 16:05:06 корпуса."""

    def test_hand_flip_that_revit_forbids_is_a_refusal_not_a_violation(self):
        """`CanFlipHand=false` обязан отказать НА МЕСТЕ, а не досидеть до
        постусловия. До починки здесь стоял `if (CanFlipHand) { flipHand(); }`
        без ветки else — недостижимый флип уходил молча, и единственным
        следом оставалось «PD: hand flip state mismatch (semantic)», то есть
        программный откат."""
        cs = _cs(_door(hand_flipped=True))
        # Проверяем именно ветку недостижимости: за `!CanFlipHand` обязан
        # стоять отказ, а не пустота.
        self.assertIn("if (!__el_PD.CanFlipHand)", cs)
        self.assertIn("__el_PD.flipHand();", cs)

    def test_facing_flip_that_revit_forbids_is_a_refusal_not_a_violation(self):
        cs = _cs(_door(facing_flipped=True))
        self.assertIn("if (!__el_PD.CanFlipFacing)", cs)
        self.assertIn("__el_PD.flipFacing();", cs)

    def test_the_refusal_names_the_family_and_the_next_move(self):
        """Отказ без следующего хода — это тупик. Сообщение обязано назвать
        и СЕМЕЙСТВО (какой именно тип не флипается), и что делать дальше."""
        cs = _cs(_door(hand_flipped=True, facing_flipped=True))
        # Имя семейства — через `FamilySymbol.Family` (документирован во всех
        # шести RevitAPI.xml), а не через `FamilySymbol.FamilyName` (0 из 6).
        self.assertIn("__sy_PD.Family.Name", cs)
        self.assertIn("выберите другой тип двери", cs)
        self.assertIn("не допускает смену стороны навески (CanFlipHand=false)",
                      cs)
        self.assertIn(
            "не допускает смену направления открывания (CanFlipFacing=false)",
            cs)

    def test_a_window_names_its_own_noun(self):
        """`_emit_hosted` обслуживает и окно — следующий ход обязан быть про
        окно, иначе совет уводит не туда."""
        cs = _cs({"op": "create_window", "id": "WN",
                  "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000,
                  "facing_flipped": True})
        self.assertIn("выберите другой тип окна", cs)

    def test_mirrored_without_a_lever_is_already_refused_at_parse_time(self):
        """Строка 12:40:36 (одинокое «PD: mirrored state mismatch») закрыта НЕ
        здесь, и это стоит зафиксировать, чтобы не чинить дважды.

        У hosted-экземпляра рычага для `Mirrored` нет вообще: с F5 v4 эмиттер
        зеркала не ставит, а `Mirrored` — признак ПРОИЗВОДНЫЙ (= Hand XOR
        Facing, живые пробы 21.07). `authoring_validation` уже отказывает на
        РАЗБОРЕ, до всякой эмиссии и до живого круга: недостижимое требование
        не доезжает до Revit."""
        out = _compile(_door(mirrored=True))
        self.assertFalse(out.ok)
        codes = {d.code for d in out.diagnostics}
        self.assertIn("KIR-T002", codes)
        self.assertTrue(any("производное состояние" in (d.message_ru or "")
                            for d in out.diagnostics))

    def test_mirrored_with_a_lever_stays_a_witnessed_consequence(self):
        """Когда флип-рычаг назван, Mirrored — следствие того, что поставили
        МЫ (= Hand XOR Facing), и проверять его законно. Отказа тут быть не
        должно, иначе мы бы отказывали в исполнимом."""
        cs = _cs(_door(mirrored=True, hand_flipped=True))
        self.assertIn("mirrored state mismatch (semantic)", cs)


class TheRefusalIsOpScopedUnderPerOp(unittest.TestCase):
    """Ради чего всё: под `per_op` отказ уносит СВОЙ оп, а не соседей."""

    def test_per_op_throws_the_op_local_sentinel(self):
        cs = _cs(_door(hand_flipped=True), isolation="per_op")
        # `refuse_stmt` — единственный владелец формы отказа; под per_op это
        # `throw __OpRefuse`, который поглощает catch этого же опа.
        self.assertIn("throw __OpRefuse(\"PD\"", cs)
        # Whole-program форма внутри обёрнутого create — запрещена (KIR-E005).
        head = cs[:cs.index("// witness")] if "// witness" in cs else cs
        self.assertNotIn("__t.RollBack(); return __Refuse(\"PD\"", head)

    def test_atomic_still_rolls_back_but_names_the_cause(self):
        cs = _cs(_door(hand_flipped=True))
        self.assertIn("__t.RollBack(); return __Refuse(\"PD\"", cs)


class TheNeverMirrorLawIsUntouched(unittest.TestCase):
    """Закон F5 v4 (`8a8c3038`) — самое дорогое знание в этом шве."""

    def test_no_mirror_call_survives_on_any_hosted_flip_combination(self):
        for kwargs in ({"mirrored": True, "hand_flipped": True},
                       {"hand_flipped": True, "facing_flipped": True},
                       {"facing_flipped": True},
                       {"mirrored": False, "hand_flipped": False,
                        "facing_flipped": False}):
            with self.subTest(**kwargs):
                self.assertNotIn("MirrorElements", _cs(_door(**kwargs)))

    def test_a_door_that_asks_for_nothing_emits_no_flip_branch_at_all(self):
        """«Отсутствующее остаётся отсутствующим»: молчащий вызывающий не
        получает ни флипа, ни отказа, ни постусловия."""
        cs = _cs(_door())
        for marker in ("CanFlipHand", "CanFlipFacing", "flipHand", "flipFacing",
                       "MirrorElements", "mirrored state mismatch",
                       "hand flip state mismatch", "facing flip state mismatch"):
            self.assertNotIn(marker, cs, marker)


if __name__ == "__main__":
    unittest.main()
