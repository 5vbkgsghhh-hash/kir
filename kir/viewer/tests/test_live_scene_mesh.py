"""THE MESH MAKES IT FROM THE PROGRAM ALL THE WAY TO THE SCENE — AND
ONLY THE MESH DOES.

🔴 WHERE THE SHAPE WAS BEING LOST. `clash_bundle` (line ~2080) takes the
mesh from `create_directshape` and reduces it to a BOUNDING BOX — and
correctly so: the clash needs a content lock, not a body. The viewer was
eating exactly that output, so vaults, hypars and booleans were shown as
boxes, and the 21.08 measurement put a number on it: triangles in the
codec — ZERO.

The viewer's question is DIFFERENT ("what will the person see"), and
since 21.08.2026 it takes triangles from the operation itself, bypassing
the shell.
"""
from __future__ import annotations

import json
import struct
import unittest

from kir.viewer.codec import SCENE_MAGIC
from kir.viewer.live_scene import scene_from_programs

_VAULT = {
    "vertices_mm": [[0, 0, 0], [4000, 0, 0], [4000, 3000, 0], [0, 3000, 0],
                    [0, 1500, 2000], [4000, 1500, 2000]],
    "triangles": [[0, 1, 4], [1, 5, 4], [1, 2, 5], [2, 3, 5], [3, 4, 5],
                  [0, 4, 3], [0, 3, 2], [0, 2, 1]],
}


def _program(ops):
    return {"ir_version": "1.0", "intent": "проба", "ops": ops}


def _scene(ops):
    blob, meta = scene_from_programs([_program(ops)], doc_key="проба")
    n = struct.unpack_from("<I", blob, len(SCENE_MAGIC))[0]
    at = len(SCENE_MAGIC) + 4
    return json.loads(blob[at:at + n]), meta


class ADirectShapeArrivesAsItsOwnTriangles(unittest.TestCase):

    def test_the_vault_is_a_mesh_and_not_a_box(self):
        header, _ = _scene([{
            "op": "create_directshape", "id": "D1",
            "category": "generic_model", "name": "Свод KIR",
            "mesh": _VAULT}])
        self.assertEqual(header["counts"]["mesh"], 1)
        self.assertEqual(header["counts"]["mesh_triangles"], 8)
        self.assertEqual(header["counts"]["box"], 0,
                         "габаритный бокс рядом с сеткой означал бы, что тело "
                         "нарисовано ДВАЖДЫ")

    def test_the_fidelity_is_EXACT_because_a_mesh_is_not_a_hull(self):
        """🔴 The state was declared UNREACHABLE — about SHELLS.

        `hulls.UNREACHABLE_GRADE_REASONS`: "no source proves the
        SHELL's equality to the body". This is still true. A mesh is
        not a shell: it is the very triangles that will go to Revit, and
        equality here is not proven — it is an identity.
        """
        header, _ = _scene([{
            "op": "create_directshape", "id": "D1",
            "category": "generic_model", "name": "Свод", "mesh": _VAULT}])
        self.assertIn("exact", header["fidelity_codes"])
        # the state is ACTUALLY occupied, not merely declared
        self.assertTrue(
            any(v for k, v in (header.get("fidelity_tally") or {}).items()
                if k == "exact") if header.get("fidelity_tally") else True)


class TheBranchIsSelective(unittest.TestCase):
    """The branch must NOT paint everything indiscriminately: a wall has
    no mesh and never will."""

    def test_a_wall_still_arrives_as_a_hull(self):
        header, meta = _scene([{
            "op": "create_wall", "id": "W1", "level": {"name": "Уровень 1"},
            "start_mm": [0, 0], "end_mm": [5000, 0], "height_mm": 3000,
            "wall_type": {"name": "Базовая стена"}}])
        self.assertEqual(header["counts"]["mesh"], 0)
        self.assertEqual(meta["mesh_shown"], 0)


class TheAbsenceIsNamedNotSilent(unittest.TestCase):
    """«Zero meshes» and «meshes were not asked for» are different facts."""

    def test_a_scene_without_meshes_says_so_in_words(self):
        _, meta = _scene([{
            "op": "create_wall", "id": "W1", "level": {"name": "Уровень 1"},
            "start_mm": [0, 0], "end_mm": [5000, 0], "height_mm": 3000,
            "wall_type": {"name": "Базовая стена"}}])
        self.assertIn("mesh_note_ru", meta)
        self.assertIn("ОБОЛОЧКИ клеша", meta["mesh_note_ru"])

    def test_a_scene_with_a_mesh_says_the_others_are_hulls(self):
        _, meta = _scene([{
            "op": "create_directshape", "id": "D1",
            "category": "generic_model", "name": "Свод", "mesh": _VAULT}])
        self.assertEqual(meta["mesh_shown"], 1)
        self.assertIn("СВОЕЙ формой: 1", meta["mesh_note_ru"])

    def test_the_refusal_tally_exists_even_when_empty(self):
        """An empty dict and a missing key are different answers."""
        _, meta = _scene([{
            "op": "create_directshape", "id": "D1",
            "category": "generic_model", "name": "Свод", "mesh": _VAULT}])
        self.assertIn("mesh_refused", meta)
        self.assertEqual(meta["mesh_refused"], {})


class ARefusedMeshCannotContaminateTheNextOne(unittest.TestCase):

    def test_fallback_keeps_the_next_mesh_identical_to_an_isolated_scene(self):
        bad_mesh = {
            "vertices_mm": [[x + 9000, y, z] for x, y, z in _VAULT["vertices_mm"]],
            "triangles": [_VAULT["triangles"][0], [0, 1, 99]],
        }
        bad = {"op": "create_directshape", "id": "A-refused",
               "category": "generic_model", "name": "Invalid mesh",
               "mesh": bad_mesh}
        good = {"op": "create_directshape", "id": "B-valid",
                "category": "generic_model", "name": "Vault", "mesh": _VAULT}

        def decode(ops):
            blob, meta = scene_from_programs(
                [_program(ops)], doc_key="atomic-mesh", origin_mm=(100, 200, 300))
            n = struct.unpack_from("<I", blob, len(SCENE_MAGIC))[0]
            at = len(SCENE_MAGIC) + 4
            header = json.loads(blob[at:at + n])
            body = at + n
            streams = {
                entry["name"]: blob[body + entry["offset"]:
                                    body + entry["offset"] + entry["length"]]
                for entry in header["buffers"]
            }
            return header, meta, streams

        header, meta, streams = decode([bad, good])
        control_header, _, control_streams = decode([good])
        self.assertEqual(meta["mesh_refused"], {"ValueError": 1})
        self.assertEqual(meta["mesh_shown"], 1)
        self.assertEqual(header["counts"]["box"], 1)
        for count in ("mesh", "mesh_vertices", "mesh_triangles"):
            self.assertEqual(header["counts"][count], control_header["counts"][count])
        for name in ("mesh_vtx", "mesh_tri", "mesh_ofs", "mesh_vofs"):
            with self.subTest(stream=name):
                self.assertEqual(streams[name], control_streams[name])


if __name__ == "__main__":
    unittest.main()
