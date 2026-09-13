"""The surface witness for `create_directshape`, EXECUTED by real .NET.

WHY A SEPARATE FILE AND A SEPARATE RUN. Everything else in `test_shape.py`
checks the PYTHON side: that the expectation is pre-registered, that it is
computed by the same canonicalizer, that a mutation changes the preimage. None of those
checks say that the C# that will actually go to Revit computes THE SAME THING.
And that is exactly where the whole class of defect lives: two canonicalizations, written in two
languages, drift apart silently, and the drift reads as a fact about Revit.

The Roslyn gate (:52412) answers only "it compiles". Here the emitted
fragment is ACTUALLY RUN: the helper block and the witness body are taken from the emitter VERBATIM
(`_MESH_CANON_HELPER_CS` and `WitnessCheck.render()`), with only stubs for the four Revit types
we do not have on Linux written around them.

THE NAMED ASSUMPTION: `MM(ft) == ft * 304.8`, `U(mm) == mm / 304.8` — the
foot↔mm conversion. The stub therefore reproduces the same double round trip as
the real path (mm literal -> P() -> feet -> Revit -> MM() -> mm); without it
the sub-grid side of the mutation would be arithmetic in a vacuum.

WHAT THIS TEST DOES NOT PROVE: that a live Revit returns from `get_Geometry`
exactly the triangles that TessellatedShapeBuilder sent it. Only a live run
can show that.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from kir.authoring import _MESH_CANON_HELPER_CS
from kir.decompile.geometry_acceptance import mesh_surface_payload
from kir.decompile.recompile import GmMesh
from kir.decompile.schema import GEOM_CANON_MM
from kir.shape_emit import _emitted_vertices, emit_directshape

_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>disable</Nullable>
    <ImplicitUsings>disable</ImplicitUsings>
    <AssemblyName>kirsurface</AssemblyName>
    <InvariantGlobalization>true</InvariantGlobalization>
  </PropertyGroup>
</Project>
"""

_STUBS = """using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

public class XYZ
{
    public double X, Y, Z;
    public XYZ(double x, double y, double z) { X = x; Y = y; Z = z; }
}
public class GeometryObject { }
public class MeshTriangle
{
    private readonly XYZ[] _v;
    public MeshTriangle(XYZ a, XYZ b, XYZ c) { _v = new XYZ[] { a, b, c }; }
    public XYZ get_Vertex(int i) { return _v[i]; }
}
public class Mesh : GeometryObject
{
    private readonly List<MeshTriangle> _t = new List<MeshTriangle>();
    public int NumTriangles { get { return _t.Count; } }
    public MeshTriangle get_Triangle(int i) { return _t[i]; }
    public void Add(MeshTriangle t) { _t.Add(t); }
}

public static class Harness
{
    static double U(double mm) { return mm / 304.8; }
    static double MM(double ft) { return ft * 304.8; }

    public static int Main(string[] args)
    {
        var __post = new List<string>();
__HELPER__
        var __mesh = new Mesh();
        string __line;
        while ((__line = Console.In.ReadLine()) != null)
        {
            __line = __line.Trim();
            if (__line.Length == 0) continue;
            string[] __p = __line.Split(' ');
            var __pts = new XYZ[3];
            for (int __i = 0; __i < 3; __i++)
                __pts[__i] = new XYZ(
                    U(double.Parse(__p[__i * 3 + 0], CultureInfo.InvariantCulture)),
                    U(double.Parse(__p[__i * 3 + 1], CultureInfo.InvariantCulture)),
                    U(double.Parse(__p[__i * 3 + 2], CultureInfo.InvariantCulture)));
            __mesh.Add(new MeshTriangle(__pts[0], __pts[1], __pts[2]));
        }
        var __ge_D1 = new List<GeometryObject>();
        __ge_D1.Add(__mesh);

__FRAGMENT__
        Console.WriteLine(__csf_D1 == null ? "<null>" : __csf_D1);
        Console.WriteLine(__post.Count.ToString(CultureInfo.InvariantCulture));
        foreach (string __v in __post) Console.WriteLine(__v);
        return 0;
    }
}
"""

#: A tetrahedron whose vertex 1 sits AT THE CENTER of the canon cell on all three
#: axes (1000.0 mm = 2000 * 0.5). Only from the center does a "below the grid" mutation
#: mean anything definite.
_VERTS = [[0.0, 0.0, 0.0], [1000.0, 0.0, 0.0],
          [0.0, 1000.0, 0.0], [0.0, 0.0, 1000.0]]
_TRIS = [[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]]


def _indent(text: str, pad: str) -> str:
    return "\n".join(pad + ln if ln.strip() else ln
                     for ln in text.splitlines())


def _surface_fragment() -> str:
    op = {"id": "D1", "mesh": {"vertices_mm": _VERTS, "triangles": _TRIS},
          "category": "mass", "name": "меш"}
    _decl, _create, checks, _rb = emit_directshape(op, "2026", "kir:test")
    for check in checks:
        if check.obligation_key == "surface":
            return check.render()
    raise AssertionError("в эмиссии нет свидетеля поверхности")


@unittest.skipIf(shutil.which("dotnet") is None,
                 "нет dotnet — исполнить эмитированный C# нечем")
class TheEmittedWitnessRunsAndAgreesWithPython(unittest.TestCase):

    work: pathlib.Path
    _tmp: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="kir-surface-cs-")
        cls.work = pathlib.Path(cls._tmp.name)
        (cls.work / "kirsurface.csproj").write_text(_CSPROJ, encoding="utf-8")
        source = (_STUBS
                  .replace("__HELPER__",
                           _indent(_MESH_CANON_HELPER_CS, "        "))
                  .replace("__FRAGMENT__", _indent(_surface_fragment(), "    ")))
        (cls.work / "Program.cs").write_text(source, encoding="utf-8")
        env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1",
                   DOTNET_NOLOGO="1")
        res = subprocess.run(
            ["dotnet", "build", "-c", "Release", "--nologo"],
            cwd=cls.work, capture_output=True, text=True, env=env, timeout=900)
        if res.returncode != 0:
            raise unittest.SkipTest(
                "dotnet build недоступен в этой среде:\n"
                + res.stdout[-2000:] + res.stderr[-1000:])

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # ── execution ──────────────────────────────────────────────────────────

    def _run(self, observed) -> tuple[str, list[str]]:
        payload = "\n".join(
            " ".join(repr(float(c)) for pt in tri for c in pt)
            for tri in observed) + "\n"
        env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1",
                   DOTNET_NOLOGO="1")
        res = subprocess.run(
            ["dotnet", "run", "-c", "Release", "--no-build", "--nologo"],
            cwd=self.work, input=payload, capture_output=True, text=True,
            env=env, timeout=900)
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        lines = res.stdout.splitlines()
        return lines[0], lines[2:2 + int(lines[1])]

    @staticmethod
    def _expected() -> str:
        verts = _emitted_vertices(_VERTS)
        return mesh_surface_payload(GmMesh(
            vertices_mm=tuple(tuple(v) for v in verts),
            triangles=tuple(tuple(t) for t in _TRIS)))

    @staticmethod
    def _observed(perturb=None, flip=False):
        verts = [list(v) for v in _emitted_vertices(_VERTS)]
        if perturb is not None:
            index, axis, delta = perturb
            verts[index][axis] += delta
        rows = [[verts[a], verts[b], verts[c]] for a, b, c in _TRIS]
        if flip:
            rows = [list(reversed(row)) for row in reversed(rows)]
        return rows

    # ── proofs ──────────────────────────────────────────────────────────

    def test_csharp_and_python_produce_the_same_preimage(self):
        observed, violations = self._run(self._observed())
        self.assertEqual(self._expected(), observed)
        self.assertEqual([], violations)

    def test_winding_and_triangle_order_do_not_matter(self):
        """The canon must be independent of traversal order and of winding —
        otherwise every Revit reassembly would read as geometry corruption."""
        observed, violations = self._run(self._observed(flip=True))
        self.assertEqual(self._expected(), observed)
        self.assertEqual([], violations)

    def test_a_shift_of_one_grid_step_fires_the_witness(self):
        for delta in (GEOM_CANON_MM, -GEOM_CANON_MM, 5.0, 400.0):
            with self.subTest(delta=delta):
                observed, violations = self._run(
                    self._observed(perturb=(1, 0, delta)))
                self.assertNotEqual(self._expected(), observed)
                self.assertEqual(1, len(violations))
                self.assertIn("surface differs", violations[0])
                self.assertIn("(geometry)", violations[0])

    def test_a_shift_below_the_half_cell_is_silent(self):
        """The reverse side of the same boundary. The cell is exactly
        `GEOM_CANON_MM` wide, the vertex sits at its center, so anything closer than
        half the step must stay in the same cell — and it does."""
        half = GEOM_CANON_MM / 2.0
        for delta in (half - 0.01, 0.2, -0.2, -(half - 0.01)):
            with self.subTest(delta=delta):
                observed, violations = self._run(
                    self._observed(perturb=(1, 0, delta)))
                self.assertEqual(self._expected(), observed)
                self.assertEqual([], violations)

    def test_the_cell_edge_itself_is_the_boundary(self):
        """Exactly half the step is already a different cell (rounding half AWAY
        FROM zero). This is precisely the tolerance: not invented, but read off the grid."""
        observed, violations = self._run(
            self._observed(perturb=(1, 0, GEOM_CANON_MM / 2.0)))
        self.assertNotEqual(self._expected(), observed)
        self.assertEqual(1, len(violations))


if __name__ == "__main__":
    unittest.main()
