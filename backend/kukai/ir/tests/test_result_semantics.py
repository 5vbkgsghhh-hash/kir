"""Typed result/effect registry and forward-reference regressions."""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"),
)

from kukai.ir import spec  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.registry_base import (  # noqa: E402
    EffectKind,
    IdentityCardinality,
    ReferenceKind,
    ResultSpec,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


class RegistryResultSemantics(unittest.TestCase):
    def test_every_op_has_a_closed_effect_and_result_contract(self):
        # 39 -> 41: wave/room (create_room_separator) и wave/opening в один
        # вечер 03.08. Число — СТОРОЖ, а не факт: оп, добавленный молча, обязан
        # уронить эту строку и заставить автора пройти весь список контрактов
        # ниже.
        # 41 -> 42: wave/wall-foundation (create_wall_foundation, 09.08).
        # Сторож сработал, список пройден: CREATE/RESULT_ELEMENT, пишущий,
        # единичная сущность с id, ссылаемый результат.
        # 42 -> 47 (09.08): волна ЭОМ/гибких/заготовок — create_conduit,
        # create_pipe_placeholder, create_duct_placeholder, create_flex_duct,
        # create_flex_pipe. ЧИСЛО ПЕРЕСНЯТО `len(spec.OPS)` НА СЛИТОМ ДЕРЕВЕ:
        # обе волны бежали от 41, и «46» из ветки ЭОМ означало бы молча
        # потерянный ленточный фундамент.
        # 47 -> 48 (09.08): create_angular_dimension. Сторож сработал, и список
        # пройден — RESULT_ELEMENT, EffectKind.CREATE, writes_model=True, плюс
        # свои строки в acceptance (OST_Dimensions), reverse_contract
        # (CAPTURE_GAP: у дуги аннотации в L0 нет ни одного входа) и
        # translation_cert (четыре обязательства, из них value — геометрия).
        # 48 -> 52 (09.08): волна нагрузок и пути эвакуации —
        # create_point_load, create_line_load, create_area_load,
        # create_path_of_travel. Сторож сработал, список пройден для всех
        # четырёх: CREATE/RESULT_ELEMENT, writes_model=True, единичная
        # сущность с id, ссылаемый результат; плюс свои строки в
        # reverse_contract (у всех четырёх CAPTURE_GAP — L0 не читает ни
        # нагрузок, ни линий пути эвакуации вовсе) и в translation_cert.
        # 52 -> 54 (09.08): волна каркаса — create_beam_system и create_truss.
        # Тот же список пройден для обоих: CREATE/RESULT_ELEMENT,
        # writes_model=True, единичная ссылаемая сущность с id; плюс свои
        # строки в acceptance (обе слепы по числу порождённого — раскладку
        # выбирает LayoutRule, стержни выбирает семейство фермы),
        # reverse_contract (обе CAPTURE_GAP: L0 несёт порождённые балки и
        # стержни, но не породившие их систему и ферму) и translation_cert
        # (пять и шесть обязательств соответственно).
        # ЧИСЛО ПЕРЕСНЯТО `len(spec.OPS)` ПОСЛЕ СЛИЯНИЯ: волны считали от 48
        # порознь (52 и 50), и взятая как есть цифра любой из них ОПУСТИЛА БЫ
        # трещотку ровно настолько, чтобы пропажа чужих опов прошла зелёной.
        # 54 -> 57 (09.08): волна площадки — create_topography,
        # create_building_pad, create_site_subregion. Семейство площадки было
        # пустым целиком: здание стояло в пустоте.
        # ЧИСЛО ПЕРЕСНЯТО `len(spec.OPS)` ПОСЛЕ СЛИЯНИЯ. Три волны назвали 52,
        # 50 и 44, и каждая была права на своей ветке — реестр рос из ОДНОГО
        # основания тремя независимыми руками в один день.
        # 57 -> 59 (09.08): волна навесных профилей — create_wall_sweep и
        # create_slab_edge. Семейство было пустым целиком: перепись реестра не
        # находила ни одной операции, создающей WallSweep, SlabEdge, Fascia
        # или Gutter, то есть карнизы, пояски, русты и капельники не
        # выражались НИЧЕМ.
        # ЧИСЛО ПЕРЕСНЯТО `len(spec.OPS)` НА ЭТОМ ДЕРЕВЕ, а не сложено с 57:
        # ровно та же дисциплина, которой требуют три абзаца выше, и ровно
        # то, что спасло бы три предыдущие волны от их столкновений.
        # 48 -> 51 (09.08): волна датумов — create_multi_segment_grid,
        # create_extrusion_roof, create_multistory_stairs. ЧИСЛО
        # ПЕРЕСНЯТО `len(spec.OPS)` НА ЭТОМ ДЕРЕВЕ, а не сложено с
        # прошлым: соседняя волна могла приехать в тот же день, и
        # «50» из ветки утопило бы её молча. Список пройден у всех
        # трёх: EffectKind.CREATE, writes_model=True, единичная
        # сущность с id (у цепи осей и лестницы результат НЕ
        # ссылаемый — на них некому ссылаться), плюс свои строки в
        # acceptance, reverse_contract и translation_cert.
        # 62 -> 64 (09.08): волна тел — create_solid_extrusion и
        # create_solid_revolve. Список пройден для обоих: RESULT_ELEMENT,
        # EffectKind.CREATE, writes_model=True, grounded=() (у DirectShape нет
        # типа — как у create_directshape), плюс свои строки в acceptance
        # (общая ветка DirectShape), reverse_contract (CAPTURE_GAP:
        # построенный B-rep не хранит профиль и высоту, которыми его написали)
        # и translation_cert (пять обязательств у каждого, из них объём и
        # площадь торцов — аналитические).
        #
        # ЗДЕСЬ ЖЕ ЧИНИТСЯ ТРЕЩОТКА, КОТОРАЯ БЫЛА КРАСНОЙ ДО ЭТОГО СЛИЯНИЯ, и
        # чинится тем самым правилом, о котором кричат абзацы выше. На базе
        # (`c98f4c72`) в этом месте стояли ПОДРЯД ДВА `assertEqual` — 59 и 51,
        # оба принесённые слиянием как «чисто аддитивные», — при настоящих 62
        # операциях в дереве. Питон исполняет первый, поэтому набор падал на
        # «59 != 62», и падал он НЕ НА ТОМ, что разошлось: сообщение говорило
        # про число опов, а дефект был в том, что две ветки написали свою
        # цифру каждая и объединение текста сохранило обе. Ровно тот же класс,
        # что дубли ключей в словаре: объединение текста — не объединение
        # смысла, и молчит оно одинаково. Утверждение теперь ОДНО, и число
        # переснято `len(spec.OPS)` на СВЕДЁННОМ дереве, а не сложено ни с
        # одной из веток: волна тел писала «50» против своей базы в 48.
        # 64 -> 65 (09.08): волна детализации — create_filled_region, ОДИН
        # оп. Сторож пройден целиком: CREATE/RESULT_ELEMENT,
        # writes_model=True, единичная ссылаемая сущность с id; плюс свои
        # строки в acceptance (сумма по OST_FilledRegion/OST_MaskingRegion —
        # маскирующая область это тот же класс, отличающийся ТИПОМ),
        # clash_bundle (тела нет: 2D-графика вида), reverse_contract
        # (CAPTURE_GAP — извлечение не читает ни одной из двух категорий) и
        # translation_cert (четыре обязательства, из них boundary — настоящая
        # геометрия, а не эхо). ОДНОЙ ВОЛНОЙ БОЛЬШЕ НЕ СТАЛО НАМЕРЕННО: марка
        # высотной отметки ОТКАЗАНА с названной причиной (пустой маркер не
        # рисует ничего, а его виды требуют ReferenceKind.VIEW — изменения
        # языка), причина записана в шапке ops_annotation.py.
        # ШЕСТОЙ РАЗ ЗА ДЕНЬ: волна писала «58» против своей базы в 57.
        # Переснято `len(spec.OPS)` на СВЕДЁННОМ дереве.
        # 65 -> 66 (10.08.2026): волна армирования — create_area_reinforcement,
        # и у него есть все четыре строки: acceptance (СЛЕПОЙ по названной
        # причине — число стержней выбирает Revit, а клетка переписи не
        # замерена), clash_bundle (тело настоящее, габарита программа не
        # несёт), reverse_contract (CAPTURE_GAP — извлечение не открывает
        # OST_AreaRein) и translation_cert (пять обязательств, из них
        # `bars_laid` УСЛОВНОЕ, потому что пустой массив при выключенной
        # HostStructuralRebar — правильный ответ по документации Autodesk).
        # ВОСЕМЬ КАНДИДАТОВ ОТКАЗАНЫ С НАЗВАННОЙ ПРИЧИНОЙ, и каждая — замер
        # компиляцией; причины записаны в шапке ops_struct.py.
        # Переснято `len(spec.OPS)` прогоном на ЭТОМ дереве.
        # 65 -> 66 (10.08.2026): волна масс — create_face_wall. ОДНОЙ ВОЛНОЙ
        # БОЛЬШЕ НЕ СТАЛО НАМЕРЕННО: шесть фабрик форм массы ОТКАЗАНЫ с
        # названной причиной (живут только на `doc.FamilyCreate`, а он
        # документирован как бросающий в проектном документе), причина
        # записана в шапке ops_mass.py.
        # 67 -> 68 (10.08.2026): площадка лестницы по эскизу.
        # CREATE/RESULT_UNREFERENCED_ELEMENT, пишущая, соло-оп;
        # добавлены acceptance, clash, reverse и certificate contracts.
        self.assertEqual(len(spec.OPS), 68)
        for name, op in spec.OPS.items():
            with self.subTest(op=name):
                self.assertIsInstance(op.effect, EffectKind)
                self.assertIsInstance(op.result, ResultSpec)
                self.assertEqual(
                    op.writes_model,
                    op.effect is not EffectKind.READ,
                )
                if op.writes_model:
                    self.assertIsNot(
                        op.result.identity_cardinality,
                        IdentityCardinality.NONE,
                    )

    def test_plural_and_special_results_are_not_reference_producers(self):
        for name in (
            "create_pipe_system",
            "route_pipe_system",
            "route_duct_system",
            "create_stairs",
            "create_group",
            "create_curtain_grid_line",
        ):
            with self.subTest(op=name):
                self.assertFalse(spec.OPS[name].result.referenceable)

    def test_reference_result_kinds_are_closed(self):
        for name, op in spec.OPS.items():
            with self.subTest(op=name):
                kind = op.result.reference_kind
                self.assertTrue(kind is None or isinstance(kind, ReferenceKind))

    def test_same_spelling_can_have_different_typed_reference_contracts(self):
        def param(op_name: str, param_name: str):
            return next(
                item for item in spec.OPS[op_name].params
                if item.name == param_name)

        self.assertEqual(
            param("create_door", "host").ref_kinds,
            (ReferenceKind.WALL,),
        )
        self.assertEqual(
            param("place_family", "host").ref_kinds,
            (ReferenceKind.ELEMENT,),
        )
        self.assertEqual(param("create_railing", "host").ref_kinds, ())
        self.assertEqual(param("create_text", "in_view").ref_kinds, ())

    def test_wire_identity_is_validated_by_declared_cardinality(self):
        single = spec.OPS["create_wall"].result
        many = spec.OPS["create_pipe_system"].result
        deleted = spec.OPS["delete"].result

        self.assertTrue(single.identity_present({"id": "42"}))
        self.assertTrue(single.identity_present({"id": 42}))
        self.assertFalse(single.identity_present({"id": ""}))
        self.assertFalse(single.identity_present({"id": True}))
        self.assertTrue(many.identity_present({"segment_ids": ["42", 43]}))
        self.assertFalse(many.identity_present({"segment_ids": []}))
        self.assertTrue(deleted.identity_present({"deleted_id": "42"}))


class TypedForwardReferences(unittest.TestCase):
    def test_place_family_is_a_referenceable_single_element_result(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "place_family",
                    "id": "PF",
                    "xyz": [0, 0, 0],
                    "level": {"by": "element_id", "value": 42},
                    "symbol": {"by": "element_id", "value": 800},
                },
                {
                    "op": "set_param",
                    "id": "S",
                    "target": {"by": "ref", "value": "PF"},
                    "param": "Comments",
                    "value": "typed-result",
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("__tg_S = (Element)__el_PF", out.csharp)

    def test_load_family_is_referenceable_without_a_create_prefix(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "load_family",
                    "id": "LF",
                    "path": r"C:\families\chair.rfa",
                    "type_name": "Chair",
                },
                {
                    "op": "set_param",
                    "id": "S",
                    "target": {"by": "ref", "value": "LF"},
                    "param": "Comments",
                    "value": "loaded-by-kir",
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("FamilySymbol __el_LF", out.csharp)
        self.assertIn("__tg_S = (Element)__el_LF", out.csharp)

    def test_plural_network_result_cannot_be_used_as_one_element(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "create_pipe_system",
                    "id": "NET",
                    "level": {"by": "element_id", "value": 42},
                    "nodes": [
                        {"id": "a", "xyz_mm": [0, 0, 0]},
                        {"id": "b", "xyz_mm": [3000, 0, 0]},
                    ],
                    "segments": [{"from": "a", "to": "b"}],
                },
                {
                    "op": "set_param",
                    "id": "S",
                    "target": {"by": "ref", "value": "NET"},
                    "param": "Comments",
                    "value": "invalid",
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertFalse(out.ok)
        diagnostic = next(item for item in out.diagnostics
                          if item.code == "KIR-L003")
        self.assertEqual(diagnostic.op_id, "S")
        self.assertEqual(diagnostic.got, "NET")

    def test_wall_only_host_rejects_a_generic_element_result(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "place_family",
                    "id": "PF",
                    "xyz": [0, 0, 0],
                    "level": {"by": "element_id", "value": 42},
                    "symbol": {"by": "element_id", "value": 800},
                },
                {
                    "op": "create_door",
                    "id": "D",
                    "host": {"by": "ref", "value": "PF"},
                    "offset_mm": 1000,
                    "symbol": {"by": "element_id", "value": 700},
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertFalse(out.ok)
        diagnostic = next(item for item in out.diagnostics
                          if item.code == "KIR-L004")
        self.assertEqual(diagnostic.expected, ["wall"])
        self.assertEqual(diagnostic.got, "element")

    def test_generic_element_consumer_accepts_a_level_subtype(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {"op": "create_level", "id": "L", "elev_mm": 9000,
                 "name": "KIR typed level"},
                {"op": "set_param", "id": "S",
                 "target": {"by": "ref", "value": "L"},
                 "param": "Comments", "value": "typed-supertype"},
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("__tg_S = (Element)__el_L", out.csharp)

    def test_nonreferenceable_view_parameter_rejects_ref_before_emit(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "element_id", "value": 42}},
                {"op": "create_text", "id": "T",
                 "in_view": {"by": "ref", "value": "W"},
                 "at": [10, 20], "content": "must refuse"},
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertFalse(out.ok)
        diagnostic = next(item for item in out.diagnostics
                          if item.field_name == "in_view")
        self.assertEqual(diagnostic.code, "KIR-T001")


if __name__ == "__main__":
    unittest.main()
