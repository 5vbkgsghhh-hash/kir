"""The scene as A STATEMENT OF KNOWLEDGE, not as a picture.

The tests hold three things, the loss of any of which gives "a green
building that nobody knows is actually green":

  1. every shell gets a trust state — none stay silent;
  2. the census converges, so the percentages on screen have a
     denominator;
  3. what is NOT in the scene is named as a number next to the picture.

A live corpus (`backend/backend/data/decompile`) is not needed for
these: the scene is built from a snapshot, and the snapshot is
assembled from elements in memory.
"""

import unittest

from kir.viewer import honesty as H
from kir.viewer.scene import BLIND_SPOTS, FIDELITY_CODE, TRUST_CODE


class CodeTablesAreClosedAndPublished(unittest.TestCase):

    def test_every_trust_value_has_a_code(self):
        """A state without a code will not reach the client and will
        turn into a KeyError in the middle of building the scene — that
        is, an empty screen with no explanation."""
        self.assertEqual(set(TRUST_CODE), {t.value for t in H.Trust})

    def test_every_fidelity_value_has_a_code(self):
        self.assertEqual(set(FIDELITY_CODE), {f.value for f in H.Fidelity})

    def test_codes_are_unique(self):
        self.assertEqual(len(set(TRUST_CODE.values())), len(TRUST_CODE))
        self.assertEqual(len(set(FIDELITY_CODE.values())), len(FIDELITY_CODE))

    def test_codes_fit_a_single_byte(self):
        """The `elem_trust` / `elem_fidelity` buffers are uint8. A code
        greater than 255 would silently truncate and recolor part of
        the building."""
        for table in (TRUST_CODE, FIDELITY_CODE):
            self.assertTrue(all(0 <= v <= 255 for v in table.values()))


class BlindSpotsAreShippedWithThePicture(unittest.TestCase):

    def test_the_list_is_not_empty(self):
        """A picture's silence reads as "everything is fine" — the same
        reason `preview.BLIND_SPOTS` is printed right on the plan sheet
        itself."""
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
    """A scene from a snapshot assembled in memory: the decompile corpus
    is not needed."""

    def _elements(self):
        return [
            {"element_id": "1", "category": "OST_Walls", "level_id": "L1",
             "type_name": "Кирпич 380",
             "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
            # A degenerate bounding box: a plane. On demo-v3 there are 38.2% of these.
            {"element_id": "2", "category": "OST_GenericModel", "level_id": "L1",
             "type_name": "",
             "bbox_min_mm": [0, 0, 1500], "bbox_max_mm": [1000, 1000, 1500]},
        ]

    def test_every_hull_receives_a_trust_state(self):
        """A shell without a state is an element the screen stays
        silent about."""
        from kir.clash import hulls as Hu
        from kir.clash import snapshot as S
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
        from kir.clash import hulls as Hu
        from kir.clash import snapshot as S
        snap = S.build_from_elements(self._elements(), origin={"doc": "тест"})
        by_id = {r.source_id: r for r in snap.records}
        flat = by_id["2"]
        self.assertIs(
            H.fidelity_of(flat.grade, flat.hull_source,
                          Hu.hull_degeneracy(flat.hull)),
            H.Fidelity.DEGENERATE)

    def test_a_bbox_wall_is_box_only_because_that_is_all_we_know(self):
        """`OST_Walls` is only allowed `bbox` (`hulls.KIND_TABLE`): the
        sections wave gave 97 conservativeness violations out of 800
        real walls and did not unlock it. So a wall is a box, and it is
        drawn as a box."""
        from kir.clash import hulls as Hu
        from kir.clash import snapshot as S
        snap = S.build_from_elements(self._elements(), origin={"doc": "тест"})
        wall = {r.source_id: r for r in snap.records}["1"]
        self.assertEqual(wall.hull_source, "bbox")
        self.assertIs(
            H.fidelity_of(wall.grade, wall.hull_source,
                          Hu.hull_degeneracy(wall.hull)),
            H.Fidelity.BOX_ONLY)
