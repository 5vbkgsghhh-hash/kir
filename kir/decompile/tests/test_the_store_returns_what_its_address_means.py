"""THE STORE RETURNS WHAT ITS HASH ADDRESSES, NOT WHOEVER ARRIVED FIRST
(F-071).

`GeometryStore.add` was fingerprinting the QUANTIZED canonical shape,
but storing `validated` — the RAW definition. When two different
geometries give the same canonical shape (a difference smaller than
`GEOM_CANON_MM = 0.5`), the SHA-256 collision guard does not fire —
`existing == canonical` — and the second element silently gets the
FIRST element's geometry.

🔴 A DEPENDENCE ON TRAVERSAL ORDER, SHOWN BY EXECUTION (before the fix):

    0.0 arrives, then 0.2  -> the store returns z=0.0
    0.2 arrives, then 0.0  -> the store returns z=0.2

The same building would be assembled with DIFFERENT geometry if the
traversal order were changed. The existing guard catches a SHA-256
collision — an event that never happens; the real event is ROUTINE, the
canon exists precisely for it.

THE FIX DOES NOT MAKE TWO CLOSE GEOMETRIES DIFFERENT — the canon does
not allow that. It makes what is returned EQUAL TO ITS OWN ADDRESS, and
sets up a merge count: otherwise a silent swap would just be replaced
by a silent rounding.

MEASURED ON LIVE SNAPSHOTS (5 `geometry.bundle.json` files, read-only):
3,106 definitions in the `geometry_store` section, ZERO merges, the
largest vertex shift 0.2500 mm — exactly half the `GEOM_CANON_MM`
quantum, i.e. a limit by construction, never exceeded.

Run:
    /opt/kir-audit/suite-venv/venv/bin/python -m pytest \
        kir/decompile/tests/test_the_store_returns_what_its_address_means.py -q
"""
from __future__ import annotations

import unittest

from kir.decompile.geom_extract import (
    GEOM_CANON_MM,
    GeometryStore,
    geometry_hash,
)


def _mesh(z: float) -> dict:
    return {"tier": "Gm",
            "vertices_mm": [[0., 0., 0.], [1000., 0., 0.], [0., 1000., z]],
            "triangles": [[0, 1, 2]]}


def _z(store: GeometryStore, key: str) -> float:
    return store.get(key).to_dict()["vertices_mm"][2][2]


#: Within the quantum — they merge by design. Beyond the quantum — they
#: must diverge.
_INSIDE = (0.0001, 0.001, 0.01, 0.04, 0.2)
_OUTSIDE = 0.6


class TheAnswerDoesNotDependOnArrivalOrder(unittest.TestCase):
    """The main property: the same address gives the same answer, no matter who arrived first."""

    def test_both_orders_give_the_same_geometry(self):
        for delta in _INSIDE:
            with self.subTest(дельта=delta):
                first = GeometryStore()
                first.add(_mesh(0.0))
                a = _z(first, first.add(_mesh(delta)))
                second = GeometryStore()
                second.add(_mesh(delta))
                b = _z(second, second.add(_mesh(0.0)))
                self.assertEqual(
                    a, b,
                    "здание собралось бы разной геометрией при другом "
                    "порядке обхода")

    def test_the_stored_value_is_the_one_the_hash_addresses(self):
        store = GeometryStore()
        key = store.add(_mesh(0.2))
        self.assertEqual(geometry_hash(store.get(key)), key,
                         "содержимое разошлось со своим адресом")

    def test_re_adding_what_was_stored_is_a_fixed_point(self):
        store = GeometryStore()
        key = store.add(_mesh(0.2))
        self.assertEqual(store.add(store.get(key)), key)
        self.assertEqual(_z(store, key), _z(store, key))


class TheCanonStillSeparatesWhatItShould(unittest.TestCase):
    """🔴 THE SECOND OUTCOME: beyond the quantum, nothing merges."""

    def test_beyond_the_canon_two_addresses_remain(self):
        self.assertNotEqual(geometry_hash(_mesh(0.0)),
                            geometry_hash(_mesh(_OUTSIDE)))
        store = GeometryStore()
        first = store.add(_mesh(0.0))
        second = store.add(_mesh(_OUTSIDE))
        self.assertNotEqual(first, second)
        self.assertNotEqual(_z(store, first), _z(store, second))

    def test_the_shift_never_exceeds_half_a_quantum(self):
        """The cost is named by a NUMBER: what is stored differs from
        the raw one by no more than half the quantum — exactly the
        amount the canon declares indistinguishable."""
        store = GeometryStore()
        for delta in (*_INSIDE, _OUTSIDE, 0.49, 0.51, 1.7):
            with self.subTest(дельта=delta):
                key = store.add(_mesh(delta))
                self.assertLessEqual(abs(_z(store, key) - delta),
                                     GEOM_CANON_MM / 2.0 + 1e-9)


class TheMergesAreCounted(unittest.TestCase):
    """A silent swap has no right to be replaced by a silent rounding."""

    def test_a_merge_is_reported_with_its_address(self):
        store = GeometryStore()
        key = store.add(_mesh(0.0))
        store.add(_mesh(0.2))
        merges = store.quantisation_collisions()
        self.assertEqual(merges, {key: 1})

    def test_the_same_definition_twice_is_not_a_merge(self):
        """🔴 THE SECOND OUTCOME: the counter counts DIFFERENT definitions, not calls."""
        store = GeometryStore()
        store.add(_mesh(0.2))
        store.add(_mesh(0.2))
        store.add(_mesh(0.2))
        self.assertEqual(store.quantisation_collisions(), {})

    def test_definitions_beyond_the_canon_are_not_a_merge(self):
        store = GeometryStore()
        store.add(_mesh(0.0))
        store.add(_mesh(_OUTSIDE))
        self.assertEqual(store.quantisation_collisions(), {})

    def test_three_distinct_definitions_under_one_address_count_two(self):
        store = GeometryStore()
        key = store.add(_mesh(0.0))
        store.add(_mesh(0.1))
        store.add(_mesh(0.2))
        self.assertEqual(store.quantisation_collisions(), {key: 2})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
