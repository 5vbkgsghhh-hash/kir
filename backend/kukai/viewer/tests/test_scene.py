"""Сцена как ЗАЯВЛЕНИЕ О ЗНАНИИ, а не как картинка.

Тесты держат три вещи, потеря каждой из которых даёт «зелёное здание, про
которое неизвестно, зелёное ли оно»:

  1. каждая оболочка получает состояние доверия — молчаливых нет;
  2. перепись сходится, значит проценты на экране имеют знаменатель;
  3. то, чего в сцене НЕТ, названо числом рядом с картинкой.

Живой корпус (`backend/backend/data/decompile`) для них не нужен: сцена
строится из снапшота, а снапшот собирается из элементов в памяти.
"""

import unittest

from kukai.viewer import honesty as H
from kukai.viewer.scene import BLIND_SPOTS, FIDELITY_CODE, TRUST_CODE


class CodeTablesAreClosedAndPublished(unittest.TestCase):

    def test_every_trust_value_has_a_code(self):
        """Состояние без кода не доедет до клиента и превратится в KeyError
        посреди постройки сцены — то есть в пустой экран без объяснения."""
        self.assertEqual(set(TRUST_CODE), {t.value for t in H.Trust})

    def test_every_fidelity_value_has_a_code(self):
        self.assertEqual(set(FIDELITY_CODE), {f.value for f in H.Fidelity})

    def test_codes_are_unique(self):
        self.assertEqual(len(set(TRUST_CODE.values())), len(TRUST_CODE))
        self.assertEqual(len(set(FIDELITY_CODE.values())), len(FIDELITY_CODE))

    def test_codes_fit_a_single_byte(self):
        """Буферы `elem_trust` / `elem_fidelity` — uint8. Код больше 255
        обрезался бы молча и перекрасил бы часть здания."""
        for table in (TRUST_CODE, FIDELITY_CODE):
            self.assertTrue(all(0 <= v <= 255 for v in table.values()))


class BlindSpotsAreShippedWithThePicture(unittest.TestCase):

    def test_the_list_is_not_empty(self):
        """Молчание картинки читается как «всё в порядке» — тот же довод, по
        которому `preview.BLIND_SPOTS` печатается на самом листе плана."""
        self.assertTrue(BLIND_SPOTS)

    def test_it_says_hulls_are_not_bodies(self):
        blob = " ".join(BLIND_SPOTS)
        self.assertIn("ОБОЛОЧКИ", blob)
        self.assertIn("exact", blob)

    def test_it_names_linked_files_and_clashes_as_absent(self):
        blob = " ".join(BLIND_SPOTS)
        self.assertIn("связанных файлов", blob)
        self.assertIn("клеши", blob)


class SceneFromSnapshot(unittest.TestCase):
    """Сцена из снапшота, собранного в памяти: корпус разборов не нужен."""

    def _elements(self):
        return [
            {"element_id": "1", "category": "OST_Walls", "level_id": "L1",
             "type_name": "Кирпич 380",
             "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
            # Вырожденный габарит: плоскость. На демо-v3 таких 38.2 %.
            {"element_id": "2", "category": "OST_GenericModel", "level_id": "L1",
             "type_name": "",
             "bbox_min_mm": [0, 0, 1500], "bbox_max_mm": [1000, 1000, 1500]},
        ]

    def test_every_hull_receives_a_trust_state(self):
        """Оболочка без состояния — элемент, про который экран молчит."""
        from kukai.clash import hulls as Hu
        from kukai.clash import snapshot as S
        snap = S.build_from_elements(self._elements(), origin={"doc": "тест"})
        census = H.HonestyCensus()
        for record in snap.records:
            fidelity = H.fidelity_of(record.grade, record.hull_source,
                                     Hu.hull_degeneracy(record.hull))
            census.add(H.ElementHonesty(record.source_id, H.Trust.UNKNOWN,
                                        fidelity))
        self.assertEqual(census.total, len(snap.records))
        self.assertTrue(census.balanced())

    def test_a_flat_bbox_is_reported_degenerate_not_shaped(self):
        from kukai.clash import hulls as Hu
        from kukai.clash import snapshot as S
        snap = S.build_from_elements(self._elements(), origin={"doc": "тест"})
        by_id = {r.source_id: r for r in snap.records}
        flat = by_id["2"]
        self.assertIs(
            H.fidelity_of(flat.grade, flat.hull_source,
                          Hu.hull_degeneracy(flat.hull)),
            H.Fidelity.DEGENERATE)

    def test_a_bbox_wall_is_box_only_because_that_is_all_we_know(self):
        """`OST_Walls` разрешён только `bbox` (`hulls.KIND_TABLE`): волна
        сечений дала 97 нарушений консервативности на 800 настоящих стенах и
        замок не открыла. Значит стена — ящик, и рисуется ящиком."""
        from kukai.clash import hulls as Hu
        from kukai.clash import snapshot as S
        snap = S.build_from_elements(self._elements(), origin={"doc": "тест"})
        wall = {r.source_id: r for r in snap.records}["1"]
        self.assertEqual(wall.hull_source, "bbox")
        self.assertIs(
            H.fidelity_of(wall.grade, wall.hull_source,
                          Hu.hull_degeneracy(wall.hull)),
            H.Fidelity.BOX_ONLY)
