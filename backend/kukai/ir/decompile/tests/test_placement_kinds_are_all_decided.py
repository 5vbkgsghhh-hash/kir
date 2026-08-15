"""КАЖДЫЙ РОД РАЗМЕЩЕНИЯ ОБЯЗАН БЫТЬ РЕШЁН, А НЕ ПРОСТО ОТСУТСТВОВАТЬ.

ПОВОД — ТРЕТИЙ СЛУЧАЙ ОДНОЙ СЕМЬИ В ОДНОМ ФАЙЛЕ. Ворота подъёма держали
закрытое множество точечных размещений, и дважды оно оказывалось уже, чем
умел оп:

  * `OneLevelBasedHosted` — «оп научился хосту, а ворота лифта не расширили»,
    2 053 элемента на башне `k2_ar_rd`;
  * `TwoLevelsBased` (12.08.2026) — оп нёс `top_level`/`base_offset_mm`/
    `top_offset_mm`, эмиттер их писал, свидетель читал `FAMILY_TOP_LEVEL_PARAM`
    обратно, а ворота отказывали 4 658 элементам. Комментарий рядом при этом
    УТВЕРЖДАЛ, что двухуровневое точкой не ставится, — при 5 337 строках с
    точкой, поворотом и обоими разрешимыми уровнями.

Родственник в воротах компиляции: производитель безусловен, потребитель за
выключенным флагом. **Две стороны одного факта развиваются порознь, и ничто
не заставляет их совпасть** — пока исключение выражено ОТСУТСТВИЕМ строки,
оно не требует решения ни от кого.

ЧЕГО ЭТОТ ТЕСТ НЕ ТРЕБУЕТ. Он не требует, чтобы все роды поднимались: у
`WorkPlaneBased` точка тоже есть (5 060 строк в той же башне), но рабочая
плоскость — отдельный факт, и подъём точкой потерял бы её молча. Замена
списка правилом «есть точка ⇒ поднимаем» запрещена именно поэтому. Требуется
РЕШЁННОСТЬ: точечный, видозависимый, либо названный отказ с причиной и сроком.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_placement_kinds.jsonl"))

from kukai.ir.decompile import lift  # noqa: E402
from kukai.ir.decompile.family_placement_extract import (  # noqa: E402
    FamilyPlacementType,
)


class EveryPlacementKindIsDecided(unittest.TestCase):

    def test_the_enum_is_reachable_before_any_zero_below(self):
        """Всякий ноль ниже был бы ложью, если перечисление пусто."""
        self.assertGreaterEqual(len(list(FamilyPlacementType)), 8)
        self.assertTrue(lift._POINT_PLACED_PLACEMENTS)
        self.assertTrue(len(lift.PLACEMENTS_NOT_POINT_PLACED))

    def test_no_placement_kind_is_silently_unhandled(self):
        """Третьего варианта — молчания — нет."""
        decided = (
            {p.value for p in lift._POINT_PLACED_PLACEMENTS}
            | {p.value for p in lift._VIEW_SPECIFIC_PLACEMENTS}
            | set(lift.PLACEMENTS_NOT_POINT_PLACED))
        silent = {p.value for p in FamilyPlacementType} - decided
        self.assertEqual(
            silent, set(),
            "роды размещения, о которых не сказано НИЧЕГО: "
            + ", ".join(sorted(silent))
            + ". Либо строка в _POINT_PLACED_PLACEMENTS (только вместе с "
              "замером, что все входы опа у них есть), либо запись в "
              "PLACEMENTS_NOT_POINT_PLACED с причиной и сроком")

    def test_a_kind_is_not_in_two_places_at_once(self):
        """Точечный И названный отказом — это два судьи об одном факте."""
        both = ({p.value for p in lift._POINT_PLACED_PLACEMENTS}
                & set(lift.PLACEMENTS_NOT_POINT_PLACED))
        self.assertEqual(both, set(),
                         "род и поднимается, и объявлен неподнимаемым: "
                         + ", ".join(sorted(both)))

    def test_the_ledger_speaks_only_about_kinds_that_exist(self):
        """Запись о роде, которого нет в перечислении, вечно зелёная и вечно
        бесполезная — тот же пробел учёта, только наоборот."""
        orphan = (set(lift.PLACEMENTS_NOT_POINT_PLACED)
                  - {p.value for p in FamilyPlacementType})
        self.assertEqual(orphan, set(),
                         "журнал говорит о несуществующих родах: "
                         + ", ".join(sorted(orphan)))

    def test_two_levels_based_is_point_placed_and_that_is_measured(self):
        """ПРИБИТО НАМЕРЕННО: прежний комментарий утверждал обратное.

        Без этой строки следующий сузит множество назад по тому же
        рассуждению — оно звучит убедительно ровно до замера.
        """
        self.assertIn(FamilyPlacementType.TWO_LEVELS_BASED,
                      lift._POINT_PLACED_PLACEMENTS)

    def test_work_plane_based_is_excluded_ON_PURPOSE_and_says_why(self):
        """Исключение, выраженное отсутствием, не требует решения ни от кого."""
        self.assertNotIn(FamilyPlacementType.WORK_PLANE_BASED,
                         lift._POINT_PLACED_PLACEMENTS)
        reason = lift.PLACEMENTS_NOT_POINT_PLACED.reason(
            FamilyPlacementType.WORK_PLANE_BASED.value)
        self.assertIn("плоскост", reason)


if __name__ == "__main__":
    unittest.main()
