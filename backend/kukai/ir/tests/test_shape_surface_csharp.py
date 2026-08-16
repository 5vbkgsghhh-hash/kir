"""Свидетель поверхности `create_directshape`, ИСПОЛНЕННЫЙ настоящим .NET.

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ И ОТДЕЛЬНЫЙ ПРОГОН. Всё остальное в `test_shape.py`
проверяет ПИТОНОВСКУЮ сторону: что ожидание пред-регистрируется, что оно
считается тем же канонизатором, что мутация меняет прообраз. Ни одна из тех
проверок не говорит, что C#, которая поедет в Revit, посчитает ТО ЖЕ САМОЕ.
А именно там и живёт весь класс дефекта: две канонизации, написанные на двух
языках, расходятся тихо, и расхождение читается как факт о Revit.

Ворота Roslyn (:52412) отвечают только «собирается». Здесь эмитированный
фрагмент ЗАПУСКАЕТСЯ: helper-блок и тело свидетеля берутся из эмиттера ДОСЛОВНО
(`_MESH_CANON_HELPER_CS` и `WitnessCheck.render()`), вокруг них дописаны только
заглушки четырёх типов Revit, которых у нас на Linux нет.

НАЗВАННОЕ ДОПУЩЕНИЕ: `MM(ft) == ft * 304.8`, `U(mm) == mm / 304.8` — перевод
фут↔мм. Заглушка поэтому воспроизводит тот же двойной проход через double, что
и настоящий путь (мм-литерал -> P() -> футы -> Revit -> MM() -> мм); без него
под-решёточная сторона мутации была бы арифметикой в вакууме.

ЧЕГО ЭТОТ ТЕСТ НЕ ДОКАЗЫВАЕТ: что живой Revit возвращает из `get_Geometry`
ровно те треугольники, которые ему послал TessellatedShapeBuilder. Это может
показать только живой прогон.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from kukai.ir.authoring import _MESH_CANON_HELPER_CS
from kukai.ir.decompile.geometry_acceptance import mesh_surface_payload
from kukai.ir.decompile.recompile import GmMesh
from kukai.ir.decompile.schema import GEOM_CANON_MM
from kukai.ir.shape_emit import _emitted_vertices, emit_directshape

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

#: Тетраэдр, у которого вершина 1 стоит В ЦЕНТРЕ ячейки канона по всем трём
#: осям (1000.0 мм = 2000 * 0.5). Только из центра мутация «ниже решётки»
#: означает что-то определённое.
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

    # ── исполнение ──────────────────────────────────────────────────────────

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

    # ── доказательства ──────────────────────────────────────────────────────

    def test_csharp_and_python_produce_the_same_preimage(self):
        observed, violations = self._run(self._observed())
        self.assertEqual(self._expected(), observed)
        self.assertEqual([], violations)

    def test_winding_and_triangle_order_do_not_matter(self):
        """Канон обязан быть независим от порядка обхода и от намотки —
        иначе всякая пересборка Revit читалась бы как порча геометрии."""
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
        """Обратная сторона той же границы. Ячейка шириной ровно
        `GEOM_CANON_MM`, вершина стоит в её центре, значит всё, что ближе
        половины шага, обязано остаться в той же ячейке — и остаётся."""
        half = GEOM_CANON_MM / 2.0
        for delta in (half - 0.01, 0.2, -0.2, -(half - 0.01)):
            with self.subTest(delta=delta):
                observed, violations = self._run(
                    self._observed(perturb=(1, 0, delta)))
                self.assertEqual(self._expected(), observed)
                self.assertEqual([], violations)

    def test_the_cell_edge_itself_is_the_boundary(self):
        """Ровно половина шага — уже другая ячейка (округление половиной ОТ
        нуля). Это и есть допуск: не изобретён, а прочитан из решётки."""
        observed, violations = self._run(
            self._observed(perturb=(1, 0, GEOM_CANON_MM / 2.0)))
        self.assertNotEqual(self._expected(), observed)
        self.assertEqual(1, len(violations))


#: Тот же тетраэдр, но вершина 1 стоит НЕ в центре ячейки, а в 0.01 мм от её
#: границы (граница — при x=1000.25, см. `_KirCanonUnit`: floor(x/0.5+0.5)
#: меняется ровно там). Ради этого сценария и ЗАВЕДЕНА ВТОРАЯ СТУПЕНЬ:
#: реальный семейственный импост 14.08.2026 стоял в точности здесь.
_EDGE_VERTS = [[0.0, 0.0, 0.0], [1000.24, 0.0, 0.0],
              [0.0, 1000.0, 0.0], [0.0, 0.0, 1000.0]]
_EDGE_TRIS = [[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]]


def _edge_fragment() -> str:
    op = {"id": "D1", "mesh": {"vertices_mm": _EDGE_VERTS, "triangles": _EDGE_TRIS},
          "category": "mass", "name": "меш"}
    _decl, _create, checks, _rb = emit_directshape(op, "2026", "kir:test")
    for check in checks:
        if check.obligation_key == "surface":
            return check.render()
    raise AssertionError("в эмиссии нет свидетеля поверхности")


@unittest.skipIf(shutil.which("dotnet") is None,
                 "нет dotnet — исполнить эмитированный C# нечем")
class TheToleranceFallbackSavesAGenuineMatchAndStillRefusesADefect(
        unittest.TestCase):
    """ВТОРАЯ СТУПЕНЬ свидетеля поверхности (14.08.2026), ИСПОЛНЕННАЯ .NET.

    `TheEmittedWitnessRunsAndAgreesWithPython` выше доказывает, что строгая
    ступень (равенство на решётке) верна и симметрична. Этот класс доказывает
    ДОПОЛНЕНИЕ к ней: когда строгая ступень ложно отвергает геометрию,
    совпадающую с точностью до сотых долей миллиметра (замер 14.08.2026 на
    живом Revit 2023: 13 из 24 реальных семейств), допусковый фолбэк её
    принимает — а геометрию, действительно отличающуюся на миллиметр,
    по-прежнему отвергает. Оба факта обязаны быть доказаны ОДНИМ прогоном
    одного и того же скомпилированного фрагмента, иначе «чинит» и «не
    ослепла» — два разных утверждения с разной ценой лжи.
    """

    work: pathlib.Path
    _tmp: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="kir-surface-tol-cs-")
        cls.work = pathlib.Path(cls._tmp.name)
        (cls.work / "kirsurface.csproj").write_text(_CSPROJ, encoding="utf-8")
        source = (_STUBS
                  .replace("__HELPER__",
                           _indent(_MESH_CANON_HELPER_CS, "        "))
                  .replace("__FRAGMENT__", _indent(_edge_fragment(), "    ")))
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
        verts = _emitted_vertices(_EDGE_VERTS)
        return mesh_surface_payload(GmMesh(
            vertices_mm=tuple(tuple(v) for v in verts),
            triangles=tuple(tuple(t) for t in _EDGE_TRIS)))

    @staticmethod
    def _observed(delta: float):
        verts = [list(v) for v in _emitted_vertices(_EDGE_VERTS)]
        verts[1][0] += delta
        return [[verts[a], verts[b], verts[c]] for a, b, c in _EDGE_TRIS]

    # ── контроль-PASS: тот самый реальный дефект, теперь спасённый ────────

    def test_a_boundary_crossing_jitter_of_0_02mm_is_accepted(self):
        """Вершина сдвинута на 0.02 мм — она ПЕРЕСЕКАЕТ границу решётки
        (1000.24 -> 1000.26), строгий прообраз меняется, но реальное
        расстояние (0.02 мм) внутри допуска 0.1 мм. Ровно класс дефекта,
        замеренный 14.08.2026 на живом импосте витража."""
        observed, violations = self._run(self._observed(delta=0.02))
        self.assertNotEqual(
            self._expected(), observed,
            "строгий прообраз ОБЯЗАН разойтись — иначе сценарий не "
            "воспроизводит границу решётки, которую чинит вторая ступень")
        self.assertEqual(
            [], violations,
            "вторая ступень обязана была принять геометрию, совпадающую "
            "с точностью 0.02мм — иначе починка не работает")

    # ── контроль-FAIL: настоящий дефект в 1мм всё ещё ловится ──────────────

    def test_a_real_1mm_defect_still_refuses(self):
        """Вершина сдвинута на 1.0 мм — заведомо выше допуска 0.1 мм и на
        порядок больше замеренного зазора (0.01-0.02 мм). Если починка
        наивно расширила бы саму решётку, а не спрашивала расстояние, этот
        тест провалился бы: ОБЯЗАН остаться красным для настоящего дефекта."""
        observed, violations = self._run(self._observed(delta=1.0))
        self.assertNotEqual(self._expected(), observed)
        self.assertEqual(1, len(violations))
        self.assertIn("surface differs", violations[0])
        self.assertIn("(geometry)", violations[0])


if __name__ == "__main__":
    unittest.main()
