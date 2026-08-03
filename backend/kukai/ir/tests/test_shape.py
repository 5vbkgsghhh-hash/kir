"""wave/shape — create_directshape: законы меша, эмиссия, round-trip, лифт.

Дисциплина пакета — сначала опровергающий тест, потом код. Здесь она соблюдена
ЧАСТИЧНО, и честнее сказать это прямо, чем сделать вид: законы формы и эмиссия
писались после ЗАМЕРА API на живом компайл-сервисе (замер и был тем шагом,
который опровергал догадки — четырёхаргументный DirectShape.CreateElement,
который написала бы память, не существует ни на одной из шести версий), а
тесты лифта (LifterReadsBackOrNamesWhy) написаны и запущены ДО лифтера и
падали ровно так, как задумано.
"""
from __future__ import annotations

import math
import unittest

from kukai.ir import spec
from kukai.ir.compiler import compile_program
from kukai.ir.mesh import (
    MAX_TRIANGLES, MESH_DEGENERATE, MESH_DISCONNECTED, MESH_DUPLICATE_FACE,
    MESH_INDEX_RANGE, MESH_UNUSED_VERTEX, validate_mesh,
)
from kukai.ir.shape_emit import parse_emitted_mesh


# ── образцы ──────────────────────────────────────────────────────────────────

def tetra() -> tuple[list, list]:
    return ([[0, 0, 0], [3000, 0, 0], [1500, 2600, 0], [1500, 900, 2400]],
            [[0, 1, 2], [0, 1, 3], [1, 2, 3], [0, 2, 3]])


def twisted_tower(sides=16, storeys=12, r0=6000.0, r1=3500.0,
                  h=36000.0, twist=140.0) -> tuple[list, list]:
    """Витая башня, порождённая математикой (см. artifacts/twisted_tower.py)."""
    verts, tris = [], []
    for k in range(storeys + 1):
        f = k / storeys
        r = r0 + (r1 - r0) * f
        a0 = math.radians(twist * f)
        for j in range(sides):
            a = a0 + 2 * math.pi * j / sides
            verts.append([r * math.cos(a), r * math.sin(a), h * f])
    for k in range(storeys):
        for j in range(sides):
            a, b = k * sides + j, k * sides + (j + 1) % sides
            c, d = (k + 1) * sides + j, (k + 1) * sides + (j + 1) % sides
            tris += [[a, b, d], [a, d, c]]
    bot = len(verts); verts.append([0.0, 0.0, 0.0])
    top = len(verts); verts.append([0.0, 0.0, h])
    for j in range(sides):
        tris.append([bot, (j + 1) % sides, j])
        tris.append([top, storeys * sides + j,
                     storeys * sides + (j + 1) % sides])
    return verts, tris


def _prog(verts, tris, category="generic_model", name="меш", oid="D1"):
    return {"ir_version": "1.0", "intent": "t",
            "ops": [{"op": "create_directshape", "id": oid,
                     "mesh": {"vertices_mm": verts, "triangles": tris},
                     "category": category, "name": name}]}


def _codes(mesh) -> list:
    diags: list = []
    out = validate_mesh(mesh, "D1", "mesh", diags)
    return [out, [d.code for d in diags]]


# ── законы формы: каждый отказ НАЗВАН, вход не правится молча ────────────────

class MeshLawsRefuseByName(unittest.TestCase):

    def test_valid_mesh_passes_unchanged(self):
        v, t = tetra()
        out, codes = _codes({"vertices_mm": v, "triangles": t})
        self.assertEqual(codes, [])
        self.assertEqual(out["triangles"], t)
        self.assertEqual(len(out["vertices_mm"]), 4)

    def test_index_out_of_range_is_named_not_clamped(self):
        v, t = tetra()
        out, codes = _codes({"vertices_mm": v, "triangles": t + [[0, 1, 99]]})
        self.assertIsNone(out)
        self.assertEqual(codes, [MESH_INDEX_RANGE])

    def test_repeated_index_is_degenerate(self):
        v, _ = tetra()
        out, codes = _codes({"vertices_mm": v, "triangles": [[0, 1, 1]]})
        self.assertIsNone(out)
        self.assertEqual(codes, [MESH_DEGENERATE])

    def test_collinear_triangle_is_degenerate(self):
        # длинные рёбра, нулевая площадь — ловится площадью, не ребром
        out, codes = _codes({"vertices_mm": [[0, 0, 0], [1000, 0, 0],
                                             [2000, 0, 0]],
                             "triangles": [[0, 1, 2]]})
        self.assertIsNone(out)
        self.assertEqual(codes, [MESH_DEGENERATE])

    def test_short_edge_is_degenerate(self):
        out, codes = _codes({"vertices_mm": [[0, 0, 0], [0.2, 0, 0],
                                             [0, 1000, 0]],
                             "triangles": [[0, 1, 2]]})
        self.assertIsNone(out)
        self.assertEqual(codes, [MESH_DEGENERATE])

    def test_duplicate_face_is_named(self):
        v, t = tetra()
        out, codes = _codes({"vertices_mm": v, "triangles": t + [[2, 1, 0]]})
        self.assertIsNone(out)
        self.assertEqual(codes, [MESH_DUPLICATE_FACE])

    def test_unused_vertex_is_named_not_dropped(self):
        v, t = tetra()
        out, codes = _codes({"vertices_mm": v + [[9000, 9000, 9000]],
                             "triangles": t})
        self.assertIsNone(out)
        self.assertEqual(codes, [MESH_UNUSED_VERTEX])

    def test_disconnected_mesh_is_named_with_component_count(self):
        v, t = tetra()
        far = [[p[0] + 500_000, p[1], p[2]] for p in v]
        out, codes = _codes({
            "vertices_mm": v + far,
            "triangles": t + [[i + 4 for i in tri] for tri in t]})
        self.assertIsNone(out)
        self.assertEqual(codes, [MESH_DISCONNECTED])

    def test_triangle_soup_is_connected_geometrically(self):
        """Каждая грань со своими вершинами — по индексам 4 куска, физически
        один. Отказать такому входу значило бы отказать самому обычному
        экспорту; связность считается по совпадению координат."""
        v, t = tetra()
        soup_v, soup_t = [], []
        for tri in t:
            base = len(soup_v)
            soup_v += [list(v[i]) for i in tri]
            soup_t.append([base, base + 1, base + 2])
        out, codes = _codes({"vertices_mm": soup_v, "triangles": soup_t})
        self.assertEqual(codes, [])
        self.assertIsNotNone(out)

    def test_over_the_measured_ceiling_is_refused(self):
        v, t = tetra()
        out, codes = _codes({"vertices_mm": v,
                             "triangles": t * (MAX_TRIANGLES // 4 + 1)})
        self.assertIsNone(out)
        self.assertTrue(codes)

    def test_non_finite_coordinate_is_refused(self):
        v, t = tetra()
        bad = [list(p) for p in v]
        bad[0][2] = float("inf")
        out, codes = _codes({"vertices_mm": bad, "triangles": t})
        self.assertIsNone(out)
        self.assertTrue(codes)

    def test_extra_field_is_refused(self):
        v, t = tetra()
        out, codes = _codes({"vertices_mm": v, "triangles": t, "colour": "red"})
        self.assertIsNone(out)
        self.assertTrue(codes)


# ── операция целиком ────────────────────────────────────────────────────────

class OpRefusesToImpersonate(unittest.TestCase):

    def test_wall_category_is_not_offered(self):
        """Меш в категории стен читается стеной в каждой спецификации, не
        будучи ничем, чем стена является. Категории нет в перечислении."""
        choices = {p.name: p.choices for p in
                   spec.OPS["create_directshape"].params}["category"]
        for impersonation in ("walls", "floors", "roofs", "columns",
                              "structural_framing", "ceilings", "stairs"):
            self.assertNotIn(impersonation, choices)

    def test_wall_category_is_a_typed_refusal_not_a_crash(self):
        v, t = tetra()
        out = compile_program(_prog(v, t, category="walls"),
                              revit_version="2023", snapshot={"levels": []})
        self.assertFalse(out.ok)
        self.assertTrue(out.diagnostics)

    def test_op_declares_geometry_not_element(self):
        op = spec.OPS["create_directshape"]
        self.assertEqual(op.capability, (("create", "geometry"),))

    def test_op_grounds_nothing_because_there_is_no_type(self):
        self.assertEqual(spec.OPS["create_directshape"].grounded, ())

    def test_name_is_required(self):
        v, t = tetra()
        prog = _prog(v, t)
        del prog["ops"][0]["name"]
        out = compile_program(prog, revit_version="2023",
                              snapshot={"levels": []})
        self.assertFalse(out.ok)


class EmissionSaysWhatItBuilt(unittest.TestCase):

    def test_compiles_on_all_six_versions_offline(self):
        v, t = tetra()
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(ver=ver):
                out = compile_program(_prog(v, t), revit_version=ver,
                                      snapshot={"levels": []})
                self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])

    def test_measured_api_names_are_the_ones_emitted(self):
        v, t = tetra()
        cs = compile_program(_prog(v, t), revit_version="2026",
                             snapshot={"levels": []}).csharp
        self.assertIn("DirectShape.CreateElement(doc, __cat_D1)", cs)
        self.assertIn("new TessellatedFace(", cs)
        # ЕДИНСТВЕННАЯ пара из поддерживаемых, которая даёт меш. RevitAPI.xml
        # (примечание к TessellatedShapeBuilder.Build, идентично в 2021 и
        # 2026): поддержаны только Solid/Abort, AnyGeometry/Mesh и
        # Mesh/Salvage. Mesh/Abort компилируется 6/6 и НЕ поддержан — этот
        # тест стоит здесь, чтобы никто не «починил» Salvage обратно на Abort
        # по тому же прямому рассуждению, по которому он был выбран сперва.
        self.assertIn("TessellatedShapeBuilderTarget.Mesh", cs)
        self.assertIn("TessellatedShapeBuilderFallback.Salvage", cs)
        self.assertNotIn("TessellatedShapeBuilderFallback.Abort", cs)
        # четырёхаргументной перегрузки не существует ни на одной версии
        self.assertNotIn('CreateElement(doc, __cat_D1, "', cs)

    def test_salvage_silence_is_closed_by_the_triangle_witness(self):
        """Salvage молчит об отброшенных гранях; единственное, что делает
        это громким, — сверка числа граней с ПОСТРОЕННЫМ элементом. Если
        свидетель исчезнет, тихое усечение вернётся."""
        v, t = tetra()
        cs = compile_program(_prog(v, t), revit_version="2023",
                             snapshot={"levels": []}).csharp
        self.assertIn("NumTriangles", cs)
        self.assertIn(f"!= {len(t)}", cs)

    def test_receipt_carries_the_honest_label(self):
        v, t = tetra()
        cs = compile_program(_prog(v, t), revit_version="2023",
                             snapshot={"levels": []}).csharp
        for field in ("bim_semantics", "has_type",
                      "schedulable_as_building_element", "human_editable",
                      "honest_label_written", "warning"):
            self.assertIn(field, cs)
        self.assertIn("геометрия без BIM-смысла", cs)

    def test_witness_reads_the_result_not_the_call(self):
        v, t = tetra()
        cs = compile_program(_prog(v, t), revit_version="2023",
                             snapshot={"levels": []}).csharp
        # габарит и число граней вычитываются С ЭЛЕМЕНТА
        self.assertIn("get_BoundingBox(null)", cs)
        self.assertIn("NumTriangles", cs)
        self.assertIn("get_Geometry(new Options())", cs)

    def test_z_extent_is_witnessed_too(self):
        """Свидетель обязан подписывать ту ось, которую читал. У меша Z —
        полноправная координата входа, и XY-свидетель перекрытий здесь бы
        подписал геометрию, которую не смотрел."""
        v, t = tetra()
        cs = compile_program(_prog(v, t), revit_version="2023",
                             snapshot={"levels": []}).csharp
        self.assertIn("Min.Z", cs)
        self.assertIn("Max.Z", cs)

    def test_post_declared_variables_survive_per_op_scope(self):
        v, t = tetra()
        for isolation in ("atomic", "per_op"):
            with self.subTest(isolation=isolation):
                out = compile_program(_prog(v, t), revit_version="2024",
                                      snapshot={"levels": []},
                                      isolation=isolation)
                self.assertTrue(out.ok)
                # обе переменные объявлены ДО блока создания
                head = out.csharp.split("using (Transaction")[0]
                self.assertIn("DirectShape __el_D1 = null;", head)
                self.assertIn("bool __lbl_D1 = false;", head)


class RoundTripThroughTheArtefact(unittest.TestCase):
    """Меш -> оп -> эмиссия -> РАЗБОР ЭМИТИРОВАННОГО C# -> тот же меш.

    Сравнение замыкается на тексте, который поедет в Revit, а не на питон-
    структуре, из которой мы его же и породили: иначе тест проверял бы
    переменную саму на себя.
    """

    def _roundtrip(self, verts, tris, tol=0.01):
        out = compile_program(_prog(verts, tris), revit_version="2026",
                              snapshot={"levels": []})
        self.assertTrue(out.ok)
        back = parse_emitted_mesh(out.csharp, "D1")
        self.assertEqual(back["triangles"], tris)
        self.assertEqual(len(back["vertices_mm"]), len(verts))
        worst = 0.0
        for a, b in zip(verts, back["vertices_mm"]):
            for ca, cb in zip(a, b):
                worst = max(worst, abs(float(ca) - float(cb)))
        self.assertLessEqual(worst, tol)
        return worst

    def test_tetra_roundtrips_within_named_tolerance(self):
        v, t = tetra()
        self.assertLessEqual(self._roundtrip(v, t), 0.01)

    def test_twisted_tower_roundtrips_within_named_tolerance(self):
        """Допуск 0.01 мм — это ровно округление координаты до двух знаков
        при эмиссии, и ничего сверх того. Названо числом, а не «примерно»."""
        v, t = twisted_tower()
        self.assertLessEqual(self._roundtrip(v, t), 0.01)

    def test_triangle_indices_survive_exactly(self):
        v, t = twisted_tower()
        out = compile_program(_prog(v, t), revit_version="2021",
                              snapshot={"levels": []})
        back = parse_emitted_mesh(out.csharp, "D1")
        self.assertEqual(back["triangles"], t)


if __name__ == "__main__":
    unittest.main()
