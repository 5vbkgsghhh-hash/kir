"""A FOURTH KIND: THE VIEWER GOT A CHANNEL OF SHAPE OF ITS OWN.

🔴 WHAT IT WAS LIKE BEFORE 21.08.2026. The viewer drew exactly three
primitives — a box, a capsule, and a prism — and all three arrived FROM THE
CLASH LAYER. That is someone else's answer to someone else's question: the
containment lock decides "do not miss an intersection", where extra volume
is cheaper than a missed one. A vault, a hypar, a boolean, and a spline
inside such a hull are indistinguishable from a box, and the measurement put
a number on it: triangles in the codec — ZERO, and of the five kinds of
nightly expressiveness, NOT A SINGLE ONE is visible.

The mesh has a FREE source: `create_directshape` carries triangles
ready-made, and `clash_bundle` honestly reduces them to a bbox — it needs no
more than that for the clash layer. The viewer's question is DIFFERENT, and
the answer to it is a mesh.
"""
from __future__ import annotations

import json
import struct
import unittest

from kir.viewer.codec import (KIND_BOX, KIND_MESH, SCENE_MAGIC, SceneBuilder,
                                encode_scene)

_TETRA_V = [(0, 0, 0), (1000, 0, 0), (0, 1000, 0), (0, 0, 1000)]
_TETRA_T = [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]


def _header(blob: bytes) -> dict:
    n = struct.unpack_from("<I", blob, len(SCENE_MAGIC))[0]
    at = len(SCENE_MAGIC) + 4
    return json.loads(blob[at:at + n])


def _scene(n_meshes: int = 1) -> tuple[SceneBuilder, bytes]:
    b = SceneBuilder(origin_mm=(0.0, 0.0, 0.0))
    for i in range(n_meshes):
        verts = [(x + i * 5000, y, z) for x, y, z in _TETRA_V]
        kind, slot = b.add_mesh(verts, _TETRA_T)
        b.add_element(element_id=f"e{i}", category="OST_GenericModel",
                      level="Уровень 1", trust=1, fidelity=1,
                      label="create_directshape", kind=kind, slot=slot,
                      axes=0, authority=0, existence=0, flags=0)
    return b, encode_scene(b, {})


class TheKindIsPublishedNotAssumed(unittest.TestCase):
    """The client reads the kind codes FROM THE HEADER, not from its own
    copy of the table."""

    def test_the_header_names_the_mesh_kind(self):
        _, blob = _scene()
        self.assertEqual(_header(blob)["kinds"]["mesh"], KIND_MESH)

    def test_the_mesh_kind_does_not_collide_with_the_older_three(self):
        kinds = _header(_scene()[1])["kinds"]
        self.assertEqual(len(set(kinds.values())), len(kinds))

    def test_the_strides_of_all_four_mesh_streams_are_published(self):
        buffers = {b["name"]: b for b in _header(_scene()[1])["buffers"]}
        for name, stride in (("mesh_vtx", 12), ("mesh_tri", 12),
                             ("mesh_ofs", 4), ("mesh_vofs", 4)):
            with self.subTest(stream=name):
                self.assertIn(name, buffers)
                self.assertEqual(buffers[name]["stride"], stride)


class TheCountsSayWhatIsThereAndWhatIsNot(unittest.TestCase):
    """🔴 "Zero meshes" and "meshes were not asked for" are different facts.

    Before 21.08, zero was true BY CONSTRUCTION, and that is exactly why no
    one noticed the window was showing clash hulls.
    """

    def test_counts_carry_meshes_triangles_and_vertices(self):
        counts = _header(_scene(3)[1])["counts"]
        self.assertEqual(counts["mesh"], 3)
        self.assertEqual(counts["mesh_triangles"], 12)
        self.assertEqual(counts["mesh_vertices"], 12)

    def test_a_scene_without_meshes_still_publishes_a_zero(self):
        b = SceneBuilder()
        kind, slot = b.add_box((0, 0, 0), (100, 100, 100))
        b.add_element(element_id="b", category="c", level=None, trust=1,
                      fidelity=1, label="create_wall", kind=kind, slot=slot,
                      axes=0, authority=0, existence=0, flags=0)
        counts = _header(encode_scene(b, {}))["counts"]
        self.assertEqual(counts["mesh"], 0)
        self.assertEqual(kind, KIND_BOX)


class TheIndicesAreGlobalAndTheOffsetsPrefixSums(unittest.TestCase):

    def test_the_second_mesh_indices_are_rebased_onto_the_shared_array(self):
        """Local indices would demand a SECOND copy of the layout from the
        client."""
        b, _ = _scene(2)
        tri = struct.unpack(f"<{len(b.mesh_tri) // 4}I", bytes(b.mesh_tri))
# the second tetrahedron has vertices 4..7
        self.assertEqual(min(tri[12:]), 4)
        self.assertEqual(max(tri[12:]), 7)

    def test_both_prefix_sums_start_at_zero_and_end_at_the_total(self):
        b, _ = _scene(3)
        ofs = struct.unpack(f"<{len(b.mesh_ofs) // 4}I", bytes(b.mesh_ofs))
        vofs = struct.unpack(f"<{len(b.mesh_vofs) // 4}I", bytes(b.mesh_vofs))
        self.assertEqual(ofs[0], 0)
        self.assertEqual(vofs[0], 0)
        self.assertEqual(ofs[-1], 12)
        self.assertEqual(vofs[-1], 12)
        self.assertEqual(len(ofs), 4)

    def test_the_origin_is_subtracted_like_every_other_kind(self):
        b = SceneBuilder(origin_mm=(1000.0, 0.0, 0.0))
        b.add_mesh([(1000, 0, 0), (2000, 0, 0), (1000, 1000, 0)],
                   [(0, 1, 2)])
        vtx = struct.unpack("<9f", bytes(b.mesh_vtx))
        self.assertAlmostEqual(vtx[0], 0.0, places=4)
        self.assertAlmostEqual(vtx[3], 1000.0, places=4)


class ABrokenTriangleIsRefusedNotSwallowed(unittest.TestCase):
    """A hole in the source must be named, not become a black spot."""

    def test_an_index_past_the_vertices_refuses_and_names_the_numbers(self):
        b = SceneBuilder()
        with self.assertRaises(ValueError) as caught:
            b.add_mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 9)])
        self.assertIn("9", str(caught.exception))
        self.assertIn("3 вершин", str(caught.exception))

    def test_a_negative_index_is_refused_too(self):
        b = SceneBuilder()
        with self.assertRaises(ValueError):
            b.add_mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, -1)])


class TheSignatureCoversWhatTheHumanSaw(unittest.TestCase):
    """The «отправить в Ревит» button signs THE THING THE HUMAN SAW."""

    def test_each_element_signs_only_ITS_OWN_mesh(self):
        """🔴 THE FIRST EDIT SIGNED ALL OF THE SCENE'S VERTICES.

        The signature grew quadratically, and the client could not
        reproduce it at all: to take "all the vertices" it would have had
        to know a layout it does not have. Equal record size is a direct
        consequence of the fix.
        """
        b, _ = _scene(3)
        sizes = {len(r) for r in b.records}
        self.assertEqual(len(sizes), 1, f"размеры подписей разошлись: {sizes}")

    def test_moving_a_vertex_changes_the_signature(self):
        """The same mesh on shifted vertices is a DIFFERENT body."""
        a = SceneBuilder()
        k, s = a.add_mesh(_TETRA_V, _TETRA_T)
        a.add_element(element_id="e", category="c", level=None, trust=1,
                      fidelity=1, label="l", kind=k, slot=s, axes=0,
                      authority=0, existence=0, flags=0)
        moved = SceneBuilder()
        shifted = [(x, y, z + 1.0) for x, y, z in _TETRA_V]
        k2, s2 = moved.add_mesh(shifted, _TETRA_T)
        moved.add_element(element_id="e", category="c", level=None, trust=1,
                          fidelity=1, label="l", kind=k2, slot=s2, axes=0,
                          authority=0, existence=0, flags=0)
        self.assertNotEqual(a.records[0], moved.records[0])

    def test_retriangulating_the_same_points_changes_the_signature(self):
        a = SceneBuilder()
        k, s = a.add_mesh(_TETRA_V, _TETRA_T)
        a.add_element(element_id="e", category="c", level=None, trust=1,
                      fidelity=1, label="l", kind=k, slot=s, axes=0,
                      authority=0, existence=0, flags=0)
        b = SceneBuilder()
        k2, s2 = b.add_mesh(_TETRA_V, [(0, 2, 1), (0, 1, 3), (0, 2, 3),
                                       (1, 2, 3)])
        b.add_element(element_id="e", category="c", level=None, trust=1,
                      fidelity=1, label="l", kind=k2, slot=s2, axes=0,
                      authority=0, existence=0, flags=0)
        self.assertNotEqual(a.records[0], b.records[0])


class TheCountHasOneCarrier(unittest.TestCase):

    def test_the_builder_names_its_own_mesh_count(self):
        """A different function assembles the header; a second counter
        there would drift apart."""
        b, blob = _scene(4)
        self.assertEqual(b.mesh_count, 4)
        self.assertEqual(_header(blob)["counts"]["mesh"], b.mesh_count)


if __name__ == "__main__":
    unittest.main()
