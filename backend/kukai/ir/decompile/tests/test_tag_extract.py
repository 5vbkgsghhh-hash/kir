"""Стадия МАРОК: провод, персистентность и ШОВ ВЕРСИЙ НА 2022.

Главное, что держит этот файл, — не форма записи, а то, что эмиссия РАЗНАЯ на
разных версиях. У цели марки нет ни одного члена, живущего во всех шести
(проверено ``tools/api_trap_index.py``, а не памятью):

    P:IndependentTag.TaggedLocalElementId       2021-2022, УДАЛЁН после 2022
    M:IndependentTag.GetTaggedLocalElementIds   2022-2026, НЕТ в 2021

Один текст, проверенный против шести целей, — это выдуманный отказ либо на
2021, либо на 2023+. Поэтому тесты ниже собирают тело ШЕСТЬ РАЗ и проверяют
каждое: ровно один вызов, тот, что на этой версии существует.
"""
from __future__ import annotations

import copy
import unittest

from kukai.ir.decompile.side_contract import (
    SIDE_FAILURE_KINDS,
    SideFailureKind,
    SideFailureReason,
    parse_wire_failures,
)
from kukai.ir.decompile.tag_extract import (
    TAG_CATEGORIES,
    TAG_EXTRACT_SCHEMA_VERSION,
    TAG_INDEX_SCHEMA_VERSION,
    TAG_SUPPORTED_VERSIONS,
    TagExtraction,
    TagFailure,
    TagPayloadError,
    TagRecord,
    build_tag_extract_cs,
    extract_tags,
    merge_tags,
)
from kukai.security.validation import validate_code_safety


def _wire(**overrides) -> dict:
    row = {
        "element_id": "4300",
        "owner_view_id": "900",
        "owner_view_name": "1 этаж",
        "at_view_ft": [10.0, -2.5],
        "tagged_element_id": "512",
        "tag_family": "independent",
        "leader": True,
        "orientation": "Horizontal",
        "type_id": "77",
        "type_name": "Марка двери",
    }
    row.update(overrides)
    return {
        "schema_version": TAG_EXTRACT_SCHEMA_VERSION,
        "elements": [row],
        "failures": [],
    }


class WireShapeTests(unittest.TestCase):

    def test_feet_become_millimetres_exactly_once(self) -> None:
        """Провод несёт СЫРЫЕ футы; пересчёт живёт в одном месте."""
        record = extract_tags(_wire()).tags[0]
        self.assertAlmostEqual(record.at_view_mm[0], 10.0 * 304.8, places=9)
        self.assertAlmostEqual(record.at_view_mm[1], -2.5 * 304.8, places=9)

    def test_bridge_envelope_is_unwrapped_once(self) -> None:
        wrapped = {"payload": _wire()}
        self.assertEqual(len(extract_tags(wrapped).tags), 1)

    def test_unexpected_field_is_a_typed_refusal(self) -> None:
        payload = _wire()
        payload["elements"][0]["at_view_mm"] = [1.0, 2.0]
        with self.assertRaises(TagPayloadError):
            extract_tags(payload)

    def test_foreign_schema_version_refuses_instead_of_half_parsing(self) -> None:
        payload = _wire()
        payload["schema_version"] = "чужая/9"
        with self.assertRaises(TagPayloadError):
            extract_tags(payload)

    def test_a_view_point_with_three_components_is_refused(self) -> None:
        """Точка вида ДВУМЕРНА: третья координата означала бы модельную точку."""
        with self.assertRaises(TagPayloadError):
            extract_tags(_wire(at_view_ft=[1.0, 2.0, 3.0]))

    def test_a_tag_without_a_target_is_refused(self) -> None:
        """Марка без цели невыразима: ``target`` у опа обязателен."""
        with self.assertRaises(TagPayloadError):
            extract_tags(_wire(tagged_element_id=""))

    def test_an_unknown_tag_family_is_refused(self) -> None:
        """Род марки — закрытый словарь: чужое значение обязано падать громко."""
        with self.assertRaises(TagPayloadError):
            extract_tags(_wire(tag_family="какой-то"))

    def test_leader_must_be_a_boolean_not_a_truthy_number(self) -> None:
        with self.assertRaises(TagPayloadError):
            extract_tags(_wire(leader=1))

    def test_a_spatial_tag_parses_as_well_as_an_independent_one(self) -> None:
        record = extract_tags(_wire(tag_family="spatial")).tags[0]
        self.assertEqual(record.tag_family, "spatial")

    def test_failures_survive_parsing(self) -> None:
        payload = _wire()
        payload["failures"] = [{
            "element_id": "4301",
            "reason": "tag marks no element of this document",
            "typed_reason": "tag_target_not_local",
        }]
        extraction = extract_tags(payload)
        self.assertEqual(len(extraction.failures), 1)
        self.assertEqual(extraction.failures[0].typed_reason,
                         "tag_target_not_local")


class TypedReasonsAreKnownToTheContractTests(unittest.TestCase):
    """Квитанция, чей тип не знает §18.2, — это молчание с лишним шагом."""

    def test_every_typed_reason_the_emitter_writes_is_in_the_vocabulary(self) -> None:
        emitted = (
            "call_budget_exhausted", "element_unresolved",
            "element_kind_mismatch", "aspect_not_present", "read_failed",
            "tag_target_not_local", "address_ambiguous",
        )
        code = build_tag_extract_cs(["1"], revit_version="2023")
        for reason in emitted:
            with self.subTest(reason=reason):
                self.assertIn(
                    f'"{reason}"', code,
                    "причина объявлена тестом, но эмиттер её не пишет")
                self.assertIn(
                    reason, {item.value for item in SideFailureReason},
                    "эмиттер пишет причину, которой нет в закрытом словаре "
                    "§18.2 — parse_wire_failures уронит весь разбор")

    def test_the_new_reason_is_classified(self) -> None:
        self.assertEqual(
            SIDE_FAILURE_KINDS[SideFailureReason.TAG_TARGET_NOT_LOCAL],
            SideFailureKind.CUT)

    def test_the_wire_failure_parses_through_the_shared_reader(self) -> None:
        failures = parse_wire_failures([{
            "element_id": "4301",
            "reason": "linked host",
            "typed_reason": "tag_target_not_local",
        }], "tag.failures")
        self.assertEqual(failures[0].typed_reason,
                         SideFailureReason.TAG_TARGET_NOT_LOCAL)


class PersistenceTests(unittest.TestCase):

    def _extraction(self) -> TagExtraction:
        return TagExtraction(
            tags=(TagRecord("4300", "900", "1 этаж", (3048.0, -762.0),
                            "512", "independent", True, "Horizontal",
                            "77", "Марка двери"),),
            failures=(TagFailure("4301", "linked host",
                                 "tag_target_not_local"),))

    def test_round_trip_through_disk_is_exact(self) -> None:
        original = self._extraction()
        restored = TagExtraction.from_json(original.to_json())
        self.assertEqual(restored.to_dict(), original.to_dict())

    def test_index_key_must_match_the_record(self) -> None:
        payload = self._extraction().to_dict()
        payload["tag_index"]["9999"] = payload["tag_index"].pop("4300")
        with self.assertRaises(TagPayloadError):
            TagExtraction.from_dict(payload)

    def test_duplicate_element_id_is_refused(self) -> None:
        record = self._extraction().tags[0]
        with self.assertRaises(TagPayloadError):
            TagExtraction(tags=(record, copy.deepcopy(record)))

    def test_persisted_schema_version_is_checked(self) -> None:
        payload = self._extraction().to_dict()
        payload["schema_version"] = "чужая/1"
        with self.assertRaises(TagPayloadError):
            TagExtraction.from_dict(payload)

    def test_the_index_answers_to_the_reconciler(self) -> None:
        """``records``/``failures`` — имена, которыми спрашивает §18.2."""
        extraction = self._extraction()
        self.assertEqual([r.element_id for r in extraction.records], ["4300"])
        self.assertEqual([f.element_id for f in extraction.failures], ["4301"])

    def test_the_persisted_version_is_its_own_literal(self) -> None:
        """Проводная и дисковая версии — РАЗНЫЕ вещи и не должны совпадать."""
        self.assertNotEqual(TAG_INDEX_SCHEMA_VERSION,
                            TAG_EXTRACT_SCHEMA_VERSION)


class MergeTests(unittest.TestCase):

    def test_first_page_wins_and_failures_accumulate(self) -> None:
        first = extract_tags(_wire(type_name="ПЕРВАЯ"))
        second = extract_tags(_wire(type_name="ВТОРАЯ"))
        payload = _wire()
        payload["elements"] = []
        payload["failures"] = [{
            "element_id": "4400", "reason": "budget",
            "typed_reason": "call_budget_exhausted"}]
        third = extract_tags(payload)
        merged = merge_tags([first, second, third])
        self.assertEqual(len(merged.tags), 1)
        self.assertEqual(merged.tags[0].type_name, "ПЕРВАЯ")
        self.assertEqual(len(merged.failures), 1)


class VersionSeamTests(unittest.TestCase):
    """ШЕСТЬ целей — шесть тел. Один текст здесь был бы выдуманным отказом."""

    #: Обращение к СВОЙСТВУ и к МЕТОДУ проверяются полными выражениями:
    #: «GetTaggedLocalElements» содержит «TaggedLocalElement» подстрокой,
    #: и наивная проверка вхождения объявила бы шов несуществующим.
    #:
    #: МЕТОД — именно ...Element*S*, а не ...ElementIds: последний возвращает
    #: ``ISet<>`` из ``System.dll``, которой нет у развёрнутого плагина
    #: (CS0012 живьём 04.08). Строка ниже — та, что это удерживает.
    PROPERTY_CALL = "__tgInd.TaggedLocalElementId"
    METHOD_CALL = "__tgInd.GetTaggedLocalElements()"
    FORBIDDEN_CALL = "__tgInd.GetTaggedLocalElementIds()"

    def test_2021_uses_the_property_that_exists_only_there(self) -> None:
        code = build_tag_extract_cs(["1"], revit_version="2021")
        self.assertIn(self.PROPERTY_CALL, code)
        self.assertNotIn(
            self.METHOD_CALL, code,
            "GetTaggedLocalElements НЕТ в 2021 — CS1061 на живой сборке")

    def test_2022_and_later_use_the_method(self) -> None:
        for version in ("2022", "2023", "2024", "2025", "2026"):
            with self.subTest(version=version):
                code = build_tag_extract_cs(["1"], revit_version=version)
                self.assertIn(self.METHOD_CALL, code)
                self.assertNotIn(
                    self.PROPERTY_CALL, code,
                    "TaggedLocalElementId УДАЛЁН после 2022 — CS1061 на 2023+")

    def test_no_version_reaches_for_the_iset_member(self) -> None:
        """Ни одна цель не зовёт член, чей ВОЗВРАТ вне замыкания клиента.

        ``GetTaggedLocalElementIds`` компилируется у нас и НЕ компилируется
        у пользователя: его ``ISet<ElementId>`` на net48 объявлен в
        ``System.dll``, которой развёрнутый плагин не ссылается. Живое
        падение 04.08 17:22:39 на 13A-RD-AR-K2_v33, отпечаток 5f48cd823928.
        """
        for version in TAG_SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                code = build_tag_extract_cs(["1"], revit_version=version)
                self.assertNotIn(self.FORBIDDEN_CALL, code)

    def test_no_body_ever_carries_both_calls(self) -> None:
        """Два вызова в одном теле не собираются НИ НА ОДНОЙ версии."""
        for version in TAG_SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                code = build_tag_extract_cs(["1"], revit_version=version)
                self.assertFalse(
                    self.PROPERTY_CALL in code and self.METHOD_CALL in code)

    def test_the_multi_reference_refusal_exists_only_where_multi_is_possible(self) -> None:
        """До 2022 марка не бывает множественной — и отказа про это там нет."""
        self.assertNotIn(
            "address_ambiguous", build_tag_extract_cs(["1"], revit_version="2021"))
        self.assertIn(
            "address_ambiguous", build_tag_extract_cs(["1"], revit_version="2022"))

    def test_an_unknown_version_falls_back_to_the_five_of_six_branch(self) -> None:
        """Версии нет ⇒ берётся член, живущий в ПЯТИ версиях, а не догадка."""
        for unknown in (None, "", "не число"):
            with self.subTest(version=unknown):
                code = build_tag_extract_cs(["1"], revit_version=unknown)
                self.assertIn(self.METHOD_CALL, code)

    def test_the_spatial_branch_is_present_on_every_version(self) -> None:
        """Марка помещения читается одинаково на всех шести: члены 6/6.

        Здесь стояло ``assertIn("__tgSpa.SpatialElement", code)``, и тест был
        зелёным всё время, пока стадия НЕ КОМПИЛИРОВАЛАСЬ НИ НА ОДНОЙ версии:
        ``CS1061: 'SpatialElementTag' does not contain a definition for
        'SpatialElement'``. Свойство описано в ``RevitAPI.xml`` всех шести и
        отсутствует в поставляемой ``RevitAPI.dll`` всех шести — тест на
        наличие ПОДСТРОКИ подтверждал ровно то же заблуждение, из которого
        текст и был написан.

        Поэтому проверяются ТРИ конкретных подкласса (единственные во всей
        иерархии), а настоящую проверку — «это компилируется» — держат
        шестиверсионные ворота, где стадия теперь есть.
        """
        for version in TAG_SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                code = build_tag_extract_cs(["1"], revit_version=version)
                self.assertNotIn("__tgSpa.SpatialElement", code)
                self.assertIn("__tgRoomTag.Room", code)
                self.assertIn("__tgAreaTag.Area", code)
                self.assertIn("__tgSpaceTag.Space", code)

    def test_an_unknown_spatial_subclass_is_named_not_swallowed(self) -> None:
        """Четвёртый подкласс — НАЗВАННЫЙ отказ, а не «цель не локальная».

        «Мы не умеем этот род марки» и «у марки нет локальной цели» — разные
        факты о разном; сложить их в одну причину значит спрятать первый за
        вторым и никогда о нём не узнать.
        """
        for version in TAG_SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                code = build_tag_extract_cs(["1"], revit_version=version)
                self.assertIn("unknown SpatialElementTag subclass", code)
                self.assertIn("element_kind_mismatch", code)


class EmittedCsTests(unittest.TestCase):

    def _code(self, version: str = "2023") -> str:
        return build_tag_extract_cs(["101", "102"], revit_version=version)

    def test_ids_and_schema_literal_are_embedded(self) -> None:
        code = self._code()
        self.assertIn('"101"', code)
        self.assertIn('"102"', code)
        self.assertIn(f'"{TAG_EXTRACT_SCHEMA_VERSION}"', code)

    def test_no_transaction_is_opened(self) -> None:
        """Стадия ЧИТАЮЩАЯ. Транзакция здесь — это запись в чужую модель."""
        code = self._code()
        self.assertNotIn("Transaction", code)
        self.assertNotIn(".Commit()", code)

    def test_every_read_is_named_by_step(self) -> None:
        """Отказ обязан называть ШАГ, а не только тип исключения."""
        code = self._code()
        self.assertIn('__tgStep = "Document.GetElement"', code)
        self.assertIn('__tgStep = "TagHeadPosition"', code)
        self.assertIn('__tgStep = "HasLeader"', code)
        self.assertIn('"tag read failed at " + __tgStep', code)

    def test_projection_uses_the_same_formula_as_the_forward_emitter(self) -> None:
        """rel = P − Origin; u = rel·Right; v = rel·Up — инверсия, не похожесть."""
        code = self._code()
        self.assertIn("__tgHead - __tgOrigin", code)
        self.assertIn("__tgRel.DotProduct(__tgRight)", code)
        self.assertIn("__tgRel.DotProduct(__tgUp)", code)

    def test_a_budgeted_page_never_runs_unbounded(self) -> None:
        code = build_tag_extract_cs(["1"], revit_version="2023",
                                    call_budget_ms=1234)
        self.assertIn("1234L", code)
        self.assertIn("call_budget_exhausted", code)

    def test_emitted_code_passes_the_safety_validator_on_every_version(self) -> None:
        for version in TAG_SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                self.assertIsNone(
                    validate_code_safety(
                        build_tag_extract_cs(["1", "2"], revit_version=version)))

    def test_empty_page_is_still_well_formed(self) -> None:
        code = build_tag_extract_cs([], revit_version="2023")
        self.assertIn("new List<string> {  }", code.replace("{ }", "{  }"))
        self.assertIsNone(validate_code_safety(code))

    def test_the_stage_declares_the_ten_measured_tag_categories(self) -> None:
        """Категории стадии обязаны совпасть с тем, что читает экстрактор."""
        from kukai.ir.decompile.extract import EXTRACT_CATEGORIES

        for category in sorted(TAG_CATEGORIES):
            with self.subTest(category=category):
                self.assertIn(
                    category, EXTRACT_CATEGORIES,
                    "стадия просит категорию, которой чтение не собирает — "
                    "id никогда не приедут")


if __name__ == "__main__":
    unittest.main()
