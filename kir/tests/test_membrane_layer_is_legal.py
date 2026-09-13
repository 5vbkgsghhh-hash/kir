"""THE OBSERVED DOCUMENT'S PROFILE WAS JUDGED BY THE CONTRACT OF WHAT WE
WRITE OURSELVES.

🔴 WHY THIS FILE EXISTS (24.08.2026, bought by LIVE REVIT, "Project2", 2026).

The law of "what layer thickness is legal" lived in TWO carriers and they
diverged:

    registry_base.WALL_LAYER_MIN_MM = 0.0    with a reasoned argument, a
        measurement, and a date: "the Membrane layer in Revit has ZERO
        thickness by construction; a 'strictly greater than zero' ban
        would reject a legitimate membrane and would be our own
        invention, not a safeguard"

    open_model.TypeSection._validate  its own literal `float(width) <= 0.0`
        -> OpenModelProfileError -> a ground refusal for the ENTIRE program

They diverged in the direction that shuts the product down. With
`KUKAI_IR_OPEN_MODEL_PREFLIGHT=1`, **every writing program on a live
document containing a membrane got refused before the transaction even
started**, and the refusal text was "the open model's snapshot violates
the typed contract" — with no field, no value, no next step. The real
reason went into `logger.debug`, and the service runs at
`--log-level info`, that is, NOWHERE.

Live measurement, verbatim, after the refusal was taught to print what it
measured:

    type_section.layers[2].width_mm must be positive,
    got 0.0 (function='Membrane', material='Air Infiltration Barrier')

A membrane is not our defect and not a corrupted document. It is a
standard vapor-barrier layer present in almost every real type catalog.
"""
from __future__ import annotations

import unittest
from unittest import mock

from kir import open_model as om
from kir import registry_base
from kir.open_model import OpenModelProfileError, TypeSection


def _section(layers):
    return TypeSection(kind="plate", source="WallType.Width",
                       thickness_mm=200.0, uniform=True, layers=layers)


#: A triple taken VERBATIM from the live "Project2," Revit 2026, 24.08.2026.
ЖИВАЯ_МЕМБРАНА = (0.0, "Membrane", "Барьер проникновению воздуха")


class МембранаЗаконна(unittest.TestCase):

    def test_живой_слой_из_Проекта2_принимается(self):
        """🔴 RED before the fix. This exact layer was shutting down the live write."""
        section = _section((
            (160.0, "Structure", "Кирпич"),
            (50.0, "Insulation", "Минвата"),
            ЖИВАЯ_МЕМБРАНА,
        ))
        self.assertEqual(section.layers[2], ЖИВАЯ_МЕМБРАНА)

    def test_нулевая_толщина_законна_у_любой_функции(self):
        """The registry declares a BOUNDARY, not a list of exceptions.

        Narrowing it to "zero only for Membrane" would mean introducing a
        THIRD carrier of the same law — the very kind of thing being
        fixed here.
        """
        self.assertEqual(registry_base.WALL_LAYER_MIN_MM, 0.0)
        _section(((0.0, "Finish1", None),))


class ГраницыОстаютсяГраницами(unittest.TestCase):

    def test_КОНТРОЛЬ_FAIL_отрицательная_толщина_по_прежнему_отказ(self):
        """Without it, the fix would mean "let everything through."""
        with self.assertRaises(OpenModelProfileError) as поймано:
            _section(((-1.0, "Structure", None),))
        self.assertIn("got -1.0", str(поймано.exception))

    def test_КОНТРОЛЬ_FAIL_толщина_выше_потолка_реестра_отказ(self):
        with self.assertRaises(OpenModelProfileError):
            _section(((registry_base.WALL_LAYER_MAX_MM + 1.0, "Structure",
                       None),))

    def test_нечисло_по_прежнему_отказ(self):
        with self.assertRaises(OpenModelProfileError):
            _section((("толсто", "Structure", None),))
        with self.assertRaises(OpenModelProfileError):
            _section(((True, "Structure", None),))


class ЗаконЖивётВРЕЕСТРЕ_АНеЗДЕСЬ(unittest.TestCase):

    def test_МУТАЦИЯ_сдвиг_границы_реестра_меняет_ответ_профиля(self):
        """🔴 This is the whole point of the exercise.

        If the profile ever reintroduces its own literal, this test will
        stay green on the shifted boundary — and will turn red exactly
        when the second carrier comes back.
        """
        with mock.patch.object(om, "WALL_LAYER_MIN_MM", 1.0):
            with self.assertRaises(OpenModelProfileError):
                _section((ЖИВАЯ_МЕМБРАНА,))
        # and conversely: at the registry boundary the same layer is legal
        _section((ЖИВАЯ_МЕМБРАНА,))

    def test_отказ_печатает_ИЗМЕРЕННОЕ_а_не_только_ожидаемое(self):
        """This refusal shuts down the entire write; the value is the only clue.

        Without it, a live investigation would run into "violates the
        contract" and stall.
        """
        with self.assertRaises(OpenModelProfileError) as поймано:
            _section(((-5.0, "Membrane", "Барьер"),))
        текст = str(поймано.exception)
        self.assertIn("got -5.0", текст)
        self.assertIn("function='Membrane'", текст)
        self.assertIn("material='Барьер'", текст)


if __name__ == "__main__":
    unittest.main()


class ПрофильНЕТЕРЯЕТПризнакНегодности(unittest.TestCase):
    """🔴 THE THIRD CASE OF ONE FORM WITHIN A DAY, found live on 24.08.2026.

    `placement_type` was introduced by the C# emission (`8b3e5f64`, the
    same day) precisely for the sake of a refusal that exhibits the
    candidates: from it you can see that a candidate is unfit BY
    CONSTRUCTION. The profile did not model it — and with
    `KUKAI_IR_OPEN_MODEL_PREFLIGHT=1` enabled, the snapshot passes through
    `OpenModelProfile.to_ground_snapshot()`, meaning a signal REVIT ITSELF
    RECORDED was being discarded BY US on the way to the consumer.

    Live measurement: the `create_adaptive_component` refusal carried five
    candidates with a category and a family and WITHOUT a placement type —
    and it is exactly the placement type that makes them unfit.
    """

    def test_признак_переживает_круговой_рейс(self):
        from kir.open_model import ModelCatalogEntry
        строка = {"id": 7, "name": "Балка", "placement_type": "CurveBased"}
        назад = ModelCatalogEntry.from_ground_row(строка).to_ground_row()
        self.assertEqual(назад.get("placement_type"), "CurveBased")

    def test_отсутствие_остаётся_отсутствием(self):
        """"We didn't read it" and "we read it, and here is what's there"
        must be distinguishable.

        And separately: `"placement_type": null` would shift the
        fingerprint of EVERY parse taken before this wave — the same
        argument as for `section`.
        """
        from kir.open_model import ModelCatalogEntry
        пустая = ModelCatalogEntry.from_ground_row({"id": 8, "name": "X"})
        self.assertIsNone(пустая.placement_type)
        self.assertNotIn("placement_type", пустая.to_ground_row())
        self.assertNotIn("placement_type", пустая.to_dict())

    def test_КОНТРОЛЬ_нестрока_отвергается(self):
        from kir.open_model import ModelCatalogEntry
        with self.assertRaises(OpenModelProfileError):
            ModelCatalogEntry.from_ground_row(
                {"id": 9, "name": "X", "placement_type": 42})

    def test_идентичность_строки_НЕ_сдвинулась(self):
        """The signal is CONTENT, not identity: `binding_digest` stays the same."""
        from kir.open_model import ModelCatalogEntry
        без = ModelCatalogEntry.from_ground_row({"id": 7, "name": "Балка"})
        с = ModelCatalogEntry.from_ground_row(
            {"id": 7, "name": "Балка", "placement_type": "CurveBased"})
        self.assertEqual(без.binding_digest, с.binding_digest)
