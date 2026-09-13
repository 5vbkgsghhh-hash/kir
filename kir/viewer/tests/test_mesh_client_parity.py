"""THE CLIENT READS THE MESH EXACTLY AS THE SERVER WROTE IT.

🔴 WHY THIS IS NOT PEDANTRY. The "send to Revit" button signs off on
WHAT THE PERSON SAW. The signature is computed by TWO sides
independently: the server — from what it sent, the panel — from its own
spliced buffers. A discrepancy here is a building the engineer never
saw, built with his consent.

For this fourth kind there are two places where this breaks most easily:

  * the mesh signature carries BOTH triangles AND vertices — an
    off-by-range miss is quiet;
  * the indices are GLOBAL, and the splice must rebase them. Forgetting
    to do so means getting someone else's triangles on your own
    vertices.

This cannot be checked by python: the splice lives on the client. That
is why `verify_mesh.mjs` lives nearby, and this file is what prepares
its input. An instrument whose inputs nobody prepares never gets run.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from kir.viewer.codec import SceneBuilder, encode_scene

_TETRA_T = [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]


def _tetra(dx: float) -> list[tuple[float, float, float]]:
    return [(dx, 0, 0), (dx + 1000, 0, 0), (dx, 1000, 0), (dx, 0, 1000)]


def _build(shifts, *, first: int = 0) -> tuple[bytes, list[str]]:
    """The scene made of meshes BY PROD CODE. Returns the blob and the
    server's signatures in hex."""
    b = SceneBuilder(origin_mm=(0.0, 0.0, 0.0))
    for i, dx in enumerate(shifts):
        kind, slot = b.add_mesh(_tetra(dx), _TETRA_T)
        b.add_element(element_id=f"e{first + i}", category="OST_GenericModel",
                      level="Уровень 1", trust=1, fidelity=1,
                      label="create_directshape", kind=kind, slot=slot,
                      axes=0, authority=0, existence=0, flags=0)
    return encode_scene(b, {}), [r.hex() for r in b.records]


class TheClientReadsWhatTheServerWrote(unittest.TestCase):

    def _run(self, module_path: pathlib.Path) -> subprocess.CompletedProcess:
        tool = pathlib.Path(__file__).with_name("verify_mesh.mjs")
        self.assertTrue(tool.exists(), "прибор не приехал вместе с тестом")
        with tempfile.TemporaryDirectory() as tmp:
            into = pathlib.Path(tmp)
            whole, records = _build([0.0, 5000.0, 10000.0])
            base, _ = _build([0.0, 5000.0])
            tail, _ = _build([10000.0], first=2)
            (into / "m_whole.bin").write_bytes(whole)
            (into / "m_base.bin").write_bytes(base)
            (into / "m_tail.bin").write_bytes(tail)
            (into / "m_records.json").write_text(
                json.dumps(records), encoding="utf-8")
            return subprocess.run(["node", str(tool), str(into),
                                   str(module_path)],
                                  capture_output=True, text=True, timeout=120)

    def _module(self) -> pathlib.Path:
        if shutil.which("node") is None:
            self.skipTest("node не установлен — прибор не запускался")
        # 🔴 THE ONLY WORKING CLIENT-SIDE KIR VERIFIER WAS LOOKING
        # DIRECTLY INTO SOMEONE ELSE'S TREE. It is green — but green
        # about the PROD copy, and in a clean venv it would have been
        # skipped by the split gate along with everything else. The
        # address now lives on one carrier: its own tree, otherwise a
        # NAMED fallback path.
        from kir.viewer.tests._client_asset import scene_data_js
        own, откуда = scene_data_js()
        if own is None:
            self.skipTest(откуда)
        return own

    def test_signatures_merge_and_geometry_all_agree(self):
        proc = self._run(self._module())
        self.assertEqual(proc.returncode, 0, f"\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("подпись поэлементно", proc.stdout)
        self.assertIn("склейка == целое", proc.stdout)

    def test_the_instrument_REDDENS_when_the_rebase_is_removed(self):
        """🔴 FAIL CONTROL, AND IT IS BEHAVIORAL.

        The REAL module is taken, and exactly the index rebase is
        removed from it — the very error being guarded here. A green
        instrument that cannot turn red is not an instrument: six of
        those were found on this tree in one evening, and one more
        today (consent broken by Cyrillic).
        """
        module = self._module()
        text = module.read_text(encoding="utf-8")
        broken = text.replace(
            "mtri[base.meshTri.length + i] = add.meshTri[i] + mvbase;",
            "mtri[base.meshTri.length + i] = add.meshTri[i];")
        self.assertNotEqual(broken, text, "мутация не нашла своё место")
        with tempfile.TemporaryDirectory() as tmp:
            hurt = pathlib.Path(tmp) / "scene-data.js"
            hurt.write_text(broken, encoding="utf-8")
            proc = self._run(hurt)
        self.assertEqual(proc.returncode, 1,
                         f"прибор не покраснел на потерянной перебазе:"
                         f"\n{proc.stdout}\n{proc.stderr}")

    def test_the_instrument_REDDENS_when_the_signature_drops_vertices(self):
        """The second mutation — the second half of the signature.

        A signature carrying only triangles would declare a mesh and
        that same mesh shifted by a kilometer to be ONE body.
        """
        module = self._module()
        text = module.read_text(encoding="utf-8")
        broken = text.replace(
            "      push(u8of(d.meshVtx, d.meshVofs[s] * 3, "
            "d.meshVofs[nextSlot[i]] * 3));\n", "")
        self.assertNotEqual(broken, text, "мутация не нашла своё место")
        with tempfile.TemporaryDirectory() as tmp:
            hurt = pathlib.Path(tmp) / "scene-data.js"
            hurt.write_text(broken, encoding="utf-8")
            proc = self._run(hurt)
        self.assertEqual(proc.returncode, 1,
                         f"прибор не покраснел на укороченной подписи:"
                         f"\n{proc.stdout}\n{proc.stderr}")


if __name__ == "__main__":
    unittest.main()
