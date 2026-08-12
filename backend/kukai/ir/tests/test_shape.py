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


# ── свидетель ПОВЕРХНОСТИ (09.08.2026) ───────────────────────────────────────

def _flat_grid(n: int = 2, step: float = 1000.0) -> tuple[list, list]:
    """Плоская сетка n×n квадратов: у неё есть ВНУТРЕННИЕ вершины.

    Именно внутренняя вершина отделяет новый свидетель от двух прежних: её
    можно унести куда угодно, не тронув ни габарит (его держат углы), ни
    число граней.
    """
    w = n + 1
    verts = [[i * step, j * step, 0.0] for i in range(w) for j in range(w)]
    tris = []
    for i in range(n):
        for j in range(n):
            a, b = i * w + j, i * w + j + 1
            c, d = (i + 1) * w + j, (i + 1) * w + j + 1
            tris += [[a, b, c], [b, d, c]]
    return verts, tris


def _expected_payload(verts, tris) -> str:
    """Прообраз, который свидетель обязан требовать, — тем же канонизатором."""
    from kukai.ir.decompile.geometry_acceptance import mesh_surface_payload
    from kukai.ir.decompile.recompile import GmMesh
    from kukai.ir.shape_emit import _emitted_vertices

    emitted = _emitted_vertices(verts)
    return mesh_surface_payload(GmMesh(
        vertices_mm=tuple(tuple(v) for v in emitted),
        triangles=tuple(tuple(t) for t in tris)))


class SurfaceWitnessIsTheExactPredicate(unittest.TestCase):
    """Число граней закрывает молчание Salvage только наполовину.

    Пересборка, сохранившая ЧИСЛО граней и сдвинувшая вершину, проходила и
    габарит, и счётчик — и снаружи это успех. Точный предикат существовал с
    первого дня Tier-G (`mesh_surface_payload`), но авторская ветка его не
    звала НИ ОДНИМ импортом. Тесты ниже держат оба конца: что предикат тот
    самый, и что он может ОТКАЗАТЬ.
    """

    def test_the_emitter_uses_the_tier_g_canonicaliser_itself(self):
        """Не «такой же», а ТОТ ЖЕ: ожидание в C# — байт в байт прообраз
        `mesh_surface_payload`, чей SHA-256 и есть `mesh_surface_digest`."""
        import hashlib

        from kukai.ir.decompile.geometry_acceptance import (
            mesh_surface_digest, mesh_surface_payload)
        from kukai.ir.decompile.recompile import GmMesh
        from kukai.ir.emit_utils import cs_string_literal
        from kukai.ir.shape_emit import _emitted_vertices

        v, t = tetra()
        cs = compile_program(_prog(v, t), revit_version="2026",
                             snapshot={"levels": []}).csharp
        self.assertIn(cs_string_literal(_expected_payload(v, t)), cs)
        gm = GmMesh(
            vertices_mm=tuple(tuple(x) for x in _emitted_vertices(v)),
            triangles=tuple(tuple(x) for x in t))
        self.assertEqual(
            hashlib.sha256(mesh_surface_payload(gm).encode("utf-8")).hexdigest(),
            mesh_surface_digest(gm))

    def test_the_expectation_is_taken_from_the_EMITTED_vertices(self):
        """Ожидание обязано считаться от вершин, которые реально уедут.

        Координата, лёгшая ближе 0.005 мм к границе ячейки канона, при
        округлении до сотых меняет ячейку. Ожидание, посчитанное от СЫРОГО
        входа, требовало бы от Revit ячейку, которую ему никто не посылал, —
        ложный отказ на верно построенном меше.
        """
        from kukai.ir.decompile.geometry_acceptance import mesh_surface_payload
        from kukai.ir.decompile.recompile import GmMesh
        from kukai.ir.emit_utils import cs_string_literal

        # 1000.2451 -> в C# уедет 1000.25 -> ячейка 2001;
        # сырое 1000.2451                  -> ячейка 2000. РАЗНЫЕ.
        v, t = tetra()
        v = [list(p) for p in v]
        v[1][0] = 1000.2451
        raw = mesh_surface_payload(GmMesh(
            vertices_mm=tuple(tuple(x) for x in v),
            triangles=tuple(tuple(x) for x in t)))
        emitted = _expected_payload(v, t)
        self.assertNotEqual(raw, emitted, "предпосылка теста: ячейки разошлись")
        cs = compile_program(_prog(v, t), revit_version="2026",
                             snapshot={"levels": []}).csharp
        self.assertIn(cs_string_literal(emitted), cs)
        self.assertNotIn(cs_string_literal(raw), cs)

    def test_a_relocated_interior_vertex_is_invisible_to_the_older_witnesses(self):
        """Тот самый случай, ради которого свидетель написан.

        Габарит держат углы, число граней не меняется — оба прежних свидетеля
        МОЛЧАТ. Прообраз поверхности меняется.
        """
        from kukai.ir.mesh import mesh_bbox

        v, t = _flat_grid(2)
        moved = [list(p) for p in v]
        moved[4][0] += 400.0                     # внутренняя вершина
        tol = spec.OPS["create_directshape"].tolerances["bbox_mm"]
        self.assertFalse(
            any(abs(a - b) > tol
                for a, b in zip(mesh_bbox(v), mesh_bbox(moved))),
            "габарит обязан остаться в допуске — иначе тест не о том")
        self.assertEqual(len(t), len(t))
        self.assertNotEqual(_expected_payload(v, t),
                            _expected_payload(moved, t))

    def test_the_canon_grid_is_the_tolerance_and_it_is_derived(self):
        """Допуск — это шаг решётки, и он НЕ выведен здесь.

        `surface_canon_mm` обязан быть равен `GEOM_CANON_MM` — замороженной
        решётке Tier-G, на которой уже стоят контентно-адресуемое хранилище
        геометрии и живой пост-коммитный предикат стенда. Разъедься они, и
        свидетель сравнивал бы два разных канона, не сказав об этом.
        """
        from kukai.ir.decompile.schema import GEOM_CANON_MM

        self.assertEqual(
            spec.OPS["create_directshape"].tolerances["surface_canon_mm"],
            GEOM_CANON_MM)

    def test_mutation_above_the_grid_fires_and_below_it_does_not(self):
        """Граница обнаружимости, обе стороны, ЧИСЛАМИ.

        Ячейка канона шириной ровно `GEOM_CANON_MM`; координата 1000.0 мм —
        её центр. Отсюда, без изобретения: сдвиг ≥ шага меняет номер ячейки
        ВСЕГДА, сдвиг < половины шага от центра не меняет его НИКОГДА.
        """
        from kukai.ir.decompile.schema import GEOM_CANON_MM

        v, t = tetra()
        v = [list(p) for p in v]
        v[1] = [1000.0, 0.0, 0.0]        # центр ячейки по всем трём осям
        base = _expected_payload(v, t)
        for delta, must_fire in (
            (GEOM_CANON_MM, True),               # 0.5 — шаг решётки
            (GEOM_CANON_MM / 2.0, True),         # 0.25 — ровно край ячейки
            (0.24, False),
            (0.2, False),
            (-0.2, False),
            (-0.24, False),
            (5.0, True),                         # допуск габарита — а он молчит
        ):
            with self.subTest(delta=delta):
                moved = [list(p) for p in v]
                moved[1][0] += delta
                fired = _expected_payload(moved, t) != base
                self.assertEqual(must_fire, fired)

    def test_the_witness_is_constructible_only_with_a_verdict(self):
        """Свидетель поверхности обязан быть в реестре обязательств и
        разряжаться КЛЮЧОМ, а не подстрокой."""
        from kukai.ir.translation_cert import (
            _ensure_table, audit_registry_coverage)

        spec_row = _ensure_table()["create_directshape"]
        self.assertEqual("model", spec_row.witness_source)
        self.assertIn("surface", {o.key for o in spec_row.obligations})
        self.assertEqual(
            (), tuple(p for p in audit_registry_coverage()
                      if "directshape" in p))

    def test_surface_check_reads_the_same_geometry_as_the_count(self):
        """Порядок проверок НЕСУЩИЙ: свидетель поверхности читает `__ge_`,
        объявленный свидетелем числа граней. Переставь их — CS0103 у
        пользователя, а не у нас."""
        from kukai.ir.shape_emit import emit_directshape

        v, t = tetra()
        op = {"id": "D1", "mesh": {"vertices_mm": v, "triangles": t},
              "category": "mass", "name": "меш"}
        _d, _c, checks, _r = emit_directshape(op, "2026", "kir:test")
        keys = [c.obligation_key for c in checks]
        self.assertEqual(["bbox", "triangles", "surface"], keys)
        declares = [c for c in checks if "var __ge_D1 =" in c.reader_cs]
        self.assertEqual(1, len(declares))
        self.assertEqual("triangles", declares[0].obligation_key)
        self.assertLess(keys.index("triangles"), keys.index("surface"))

    def test_no_hash_is_emitted_because_the_client_cannot_bind_one(self):
        """Замер :52412 (09.08): `System.Security.Cryptography.SHA256` даёт
        CS1069 на 2025 и 2026 — тип переадресован в сборку вне замыкания
        ссылок клиента. Эмитировать хеш нельзя; сравнивается прообраз."""
        v, t = tetra()
        cs = compile_program(_prog(v, t), revit_version="2026",
                             snapshot={"levels": []}).csharp
        self.assertNotIn("Cryptography", cs)
        self.assertNotIn("SHA256", cs)
        self.assertIn("__KirCanonPayload(", cs)

    def test_the_helper_is_absent_when_nothing_calls_it(self):
        """Отсутствие остаётся отсутствием: программа без меша обязана быть
        байт в байт прежней (тот же закон, что у `__ClassName`)."""
        wall = {"ir_version": "1.0", "intent": "t",
                "ops": [{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                         "p1_mm": [6000, 0], "height_mm": 3000,
                         "level": {"by": "element_id", "value": 42}}]}
        cs = compile_program(wall, revit_version="2026",
                             snapshot={"levels": []}).csharp
        self.assertNotIn("__KirCanonUnit", cs)
        self.assertNotIn("__KirCanonPayload", cs)

    def test_a_face_that_the_emission_grid_collapses_is_a_typed_refusal(self):
        """Округление до сотых может СХЛОПНУТЬ иглу, которую законы mesh.py
        пропускают (min ребро 1 мм, min площадь 1 мм²). Такой меш уехал бы в
        Revit вырожденной гранью — здесь названный отказ, а не тихая потеря
        свидетеля."""
        # основание 1000 мм, высота 0.002 мм: площадь 1 мм², min ребро ~500 мм
        verts = [[0.0, 0.0, 0.0], [1000.0, 0.0, 0.0], [500.0, 0.002, 0.0],
                 [500.0, 400.0, 800.0]]
        tris = [[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]]
        diags: list = []
        self.assertIsNotNone(
            validate_mesh({"vertices_mm": verts, "triangles": tris},
                          "D1", "mesh", diags),
            "предпосылка теста: законы формы этот меш ПРОПУСКАЮТ")
        out = compile_program(_prog(verts, tris), revit_version="2026",
                              snapshot={"levels": []})
        self.assertFalse(out.ok)
        self.assertEqual([MESH_DEGENERATE], [d.code for d in out.diagnostics])
        self.assertEqual("D1", out.diagnostics[0].op_id)


if __name__ == "__main__":
    unittest.main()
