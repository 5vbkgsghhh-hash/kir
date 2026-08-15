"""МАРКА ПОМЕЩЕНИЯ — ДРУГОЙ КЛАСС, И РАЗЛИЧАЕТ ИХ ЦЕЛЬ, А НЕ АВТОР.

ЗАЧЕМ. Замерено 13.08.2026 на `len_ar_me_r24_v1` — втором жилом здании,
прочитанном полностью (все десять стадий, 57 809 элементов): **7 067**
элементов уходили в атом `unsupported_forward_signature` с одной причиной —
«марка рода `spatial` — это SpatialElementTag (помещение/площадь/
пространство), а прямой ход строит марку единственным способом,
IndependentTag.Create». Это крупнейшая причина этого рода на здании.

Обратный ход был готов с 30.07: `tag_extract` читает ОБА рода и снимает вид,
точку, цель, выноску и тип. Отказывал ЛИФТ, и отказывал НАМЕРЕННО, назвав
маршрут. Дыра была в ПРЯМОМ ходе.

ЧТО ЗАКРЕПЛЕНО ЗДЕСЬ — форма испущенного C#, а не поведение Ревита. Живьём оп
НЕ ПРОВЕРЕН, и это сказано вслух: в каких осях `UV` у `NewRoomTag`,
компиляцией не устанавливается. Догадка была бы молча смещённой маркой,
поэтому точка не додумывается — свидетель `head_at` читает `TagHeadPosition`
обратно ТЕМ ЖЕ базисом вида, каким она клалась, и неверная ось даст
ТИПИЗИРОВАННОЕ НАРУШЕНИЕ, а не тихий сдвиг.

ШЕСТЬ ВЕРСИЙ закрыты компиляцией отдельно (13.08): программа со стеной и
маркой собирается 6/6; контроли `NewRoomTagZZZ` и `RoomTag.RoomZZZ` дают
6/6 CS1061 — то есть ветка не мертва и её члены не выдуманы.
"""

from __future__ import annotations

import unittest

from kukai.ir.compiler import compile_program


def _emit(revit_version: str = "2026", **tag_extra: object) -> str:
    tag: dict[str, object] = {
        "op": "create_tag", "id": "TAG1",
        "in_view": {"by": "element_id", "value": 900},
        "target": {"by": "ref", "value": "W1"},
        "at": [3000, 800],
    }
    tag.update(tag_extra)
    program = {"ir_version": "1.0", "ops": [
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "height_mm": 3000, "level": {"by": "element_id", "value": 100}},
        tag,
    ]}
    out = compile_program(program, revit_version=revit_version,
                          snapshot=None, bulk=True)
    assert out.ok, [d.as_dict() for d in (out.diagnostics or [])][:3]
    return out.csharp


class TheBranchIsChosenByTheTargetAtRuntime(unittest.TestCase):
    """Класс марки следует из цели, и решает это Ревит, а не мы."""

    def setUp(self) -> None:
        self.cs = _emit()

    def test_the_target_is_asked_whether_it_is_spatial(self) -> None:
        # Ветка стоит в C#, а не в питоне, ПО ПОСТРОЕНИЮ: у `create_tag.target`
        # нет пула (`ref_kinds=ELEMENT`), класс цели на эмиссии неизвестен.
        self.assertIn("as SpatialElement", self.cs)

    def test_each_spatial_kind_has_its_own_creator(self) -> None:
        for member in ("NewRoomTag", "NewSpaceTag", "NewAreaTag"):
            with self.subTest(member):
                self.assertIn(member, self.cs)

    def test_the_independent_path_is_untouched(self) -> None:
        # Ветка ДОБАВЛЕНА, а не заменила прежнюю: 851 марка корпуса и весь
        # прежний свидетель обязаны ехать по старой дороге байт в байт.
        self.assertIn("IndependentTag.Create(", self.cs)

    def test_the_base_property_absent_from_the_dlls_is_never_asked(self) -> None:
        # Случай #78: `SpatialElementTag.SpatialElement` описан в шести XML и
        # ОТСУТСТВУЕТ в шести DLL. Боковая стадия обожглась на нём 30.07 —
        # тело не компилировалось НИ НА ОДНОЙ версии, то есть марки не
        # читались нигде. Цель берётся у ПОДКЛАССА.
        self.assertNotIn(".SpatialElement;", self.cs)
        self.assertNotIn(".SpatialElement ", self.cs)


class EveryRefusalNamesItsSubject(unittest.TestCase):
    """Отказ проектировался вместе с успехом, а не после него."""

    def setUp(self) -> None:
        self.cs = _emit()

    def test_an_unplaced_spatial_element_is_refused(self) -> None:
        # Ревит на неразмещённом помещении даёт МУСОР, а не ошибку, — потому
        # проверка наша, а не его.
        self.assertIn("НЕ РАЗМЕЩЁН", self.cs)
        self.assertIn(".Location == null", self.cs)

    def test_a_leader_is_refused_with_its_reason(self) -> None:
        # У марки С выноской точка означает КОНЕЦ ВЫНОСКИ, а сверяется
        # ГОЛОВА. Молчаливый увод головы сравнением по голове не ловится.
        self.assertIn("КОНЕЦ ВЫНОСКИ", _emit(leader=True))

    def test_the_leader_guard_is_absent_when_no_leader_was_asked(self) -> None:
        """Сторож без повода — мёртвая ветка, а не запас прочности.

        Первая редакция писала `if (false) { отказ }` всегда: константно-
        ложный сторож. У свидетелей ровно эту форму отвергает
        `translation_cert.analyze_witness_cs`; в создании сертификат не
        смотрит, и она жила бы незамеченной. Проверяется ОБЕ стороны —
        появляется по запросу и отсутствует без него.
        """
        self.assertNotIn("КОНЕЦ ВЫНОСКИ", self.cs)
        self.assertNotIn("if (false)", self.cs)

    def test_an_area_outside_a_plan_view_is_refused_by_the_view_kind(self) -> None:
        self.assertIn("ViewPlan", self.cs)
        # Отказ обязан назвать ФАКТИЧЕСКИЙ род вида, а не сказать «не тот вид»:
        # иначе следующий ход читателю неизвестен.
        self.assertIn(".ViewType.ToString()", self.cs)

    def test_an_unknown_spatial_kind_is_refused_rather_than_left_null(self) -> None:
        # Без этой ветки `__el_` остался бы null, и причина потерялась бы за
        # общим «вернул null».
        self.assertIn(".GetType().Name", self.cs)


class TheWitnessReadsTheClassThatCarriesTheAnswer(unittest.TestCase):

    def setUp(self) -> None:
        self.cs = _emit()

    def test_the_binding_is_read_from_each_subclass(self) -> None:
        for member in (".Room", ".Area", ".Space"):
            with self.subTest(member):
                self.assertIn(member, self.cs)

    def test_the_head_is_read_from_whichever_class_the_tag_is(self) -> None:
        self.assertIn("as IndependentTag", self.cs)
        self.assertIn("SpatialElementTag)", self.cs)

    def test_the_head_goes_through_the_same_view_basis_as_the_placement(self) -> None:
        # Инверсия обязана быть ТОЧНОЙ, а не похожей формулой в другом месте:
        # иначе неверная ось `UV` осталась бы невидимой, а она — единственное,
        # чего мы про этот оп не знаем.
        self.assertIn("RightDirection", self.cs)
        self.assertIn("UpDirection", self.cs)


class TheVersionSurfaceDidNotMove(unittest.TestCase):
    """Место отказа по версии осталось ровно одно, и это проверяется.

    `tag_type` на 2021 отказывался и отказывается на ЭМИССИИ (`IndependentTag.
    Create(symId,...)` появился в 2022). У пространственной марки тип ставится
    `ChangeTypeId` уже ПОСЛЕ создания, и соблазн был перенести отказ в
    выполнение. Перенос сдвинул бы поверхность хрупкости по версии, за которой
    следит `test_version_fragile_asks_the_emitter`, — поэтому поведение 2021
    не тронуто ни на байт.
    """

    def test_tag_type_on_2021_is_still_an_emit_time_refusal(self) -> None:
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
             "height_mm": 3000, "level": {"by": "element_id", "value": 100}},
            {"op": "create_tag", "id": "TAG1",
             "in_view": {"by": "element_id", "value": 900},
             "target": {"by": "ref", "value": "W1"}, "at": [3000, 800],
             "tag_type": {"by": "element_id", "value": 777}},
        ]}
        out = compile_program(program, revit_version="2021",
                              snapshot=None, bulk=True)
        self.assertFalse(out.ok)
        codes = {d.code for d in (out.diagnostics or ())}
        self.assertIn("KIR-E003", codes)

    def test_the_type_is_applied_after_creation_only_when_asked(self) -> None:
        self.assertNotIn("ChangeTypeId", _emit())
        self.assertIn("ChangeTypeId",
                      _emit(revit_version="2022",
                            tag_type={"by": "element_id", "value": 777}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
