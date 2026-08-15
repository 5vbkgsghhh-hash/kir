"""ПРИНАДЛЕЖНОСТЬ ЛИНИИ: «не определено» обязано отличаться от «не снималось».

ЗАЧЕМ ЭТОТ ФАЙЛ. ``OST_Lines`` держит в одной категории модельные линии
(авторская геометрия) и линии детализации (оформление). Замерено 13.08.2026 на
`k2_ar_rd_v7`: 9 407 элементов этой категории, у ВСЕХ пустой ``type_name``, у
ВСЕХ отсутствует уровень, а геометрия ЕСТЬ — 9 256 кривых с концами и 151
габарит. Недоставало ровно ПРИНАДЛЕЖНОСТИ: у линии есть где, но неизвестно
чья. `tools/content_coverage.py` относит всю категорию к оформлению и говорит
об этом в своей же строке: «по большинству в реальных РД». Это оценка, а не
замер, и полоса главного числа проекта держится на ней.

ЧТО ЗДЕСЬ ЗАКРЕПЛЕНО — не факт о зданиях, а форма поля: ТРИ состояния должны
быть различимы ПО ПОСТРОЕНИЮ, иначе пустое поле снова начнёт означать три
разные правды. Каждая проверка идёт парой «контроль-PASS + контроль-FAIL»: без
второй половины зелёный цвет ничего не сообщает (форма 8 канона).

ГРАНИЦА. Файл проверяет КОНТРАКТ (схема L0 и текст эмитируемого C#). Он не
проверяет, что Revit отвечает верно, — это вопрос живого прогона, и никакой
офлайн-тест на него не отвечает. Шесть версий закрыты компиляцией через
`gate_runner` (замерено 13.08: опыт 6/6 зелёных, контроль `SketchPlaneZZZ`
6/6 красных, CS1061 на той же строке).
"""

from __future__ import annotations

import unittest

from kukai.ir.decompile.geometry_store import GEOMETRY_HELPER_CS
from kukai.ir.decompile.schema import L0Element, L0SchemaError, LineOwner


def _row(**overrides: object) -> dict[str, object]:
    """Строка L0 категории `OST_Lines`.

    Взят габаритный вид (151 из 9 407), потому что он проще: принадлежность
    ортогональна геометрии, и проверять её на кривой значило бы тащить в
    каждый случай лишние обязательные поля. Что поле живёт и на кривой,
    закреплено отдельно — :meth:`ThreeStatesAreDistinguishable.
    test_the_field_is_orthogonal_to_geometry`.
    """

    row: dict[str, object] = {
        "element_id": "1001",
        "category": "OST_Lines",
        "category_ru": "Линии",
        "type_id": "2002",
        "type_name": "",
        "level_id": None,
        "level_name": None,
        "geom_kind": "bbox_only",
        "p0_mm": None,
        "p1_mm": None,
        "rotation_deg": None,
        "bbox_min_mm": [0.0, 0.0, 0.0],
        "bbox_max_mm": [1000.0, 0.0, 0.0],
        "host_id": None,
        "params": {},
    }
    row.update(overrides)
    return row


class ThreeStatesAreDistinguishable(unittest.TestCase):
    """«Не снималось», «не определено» и определённый владелец — три разных."""

    def test_absent_key_reads_as_not_measured(self) -> None:
        element = L0Element.from_dict(_row())
        self.assertIsNone(element.line_owner_kind)
        # И обратно: то, чего не снимали, не пишется — иначе замороженный L0
        # начал бы выглядеть измеренным.
        self.assertNotIn("line_owner_kind", element.to_dict())

    def test_undecided_is_a_typed_refusal_not_an_empty_field(self) -> None:
        element = L0Element.from_dict(
            _row(line_owner_kind="none", line_owner_id=None))
        self.assertIs(element.line_owner_kind, LineOwner.NONE)
        # Контроль-различение: это состояние ОБЯЗАНО быть отличимо от
        # предыдущего в сериализованной строке, а не только в объекте.
        self.assertIn("line_owner_kind", element.to_dict())
        self.assertNotEqual(
            L0Element.from_dict(_row()).to_dict().get("line_owner_kind"),
            element.to_dict()["line_owner_kind"])

    def test_both_owners_carry_their_id(self) -> None:
        for value, expected in (
            ("view", LineOwner.VIEW),
            ("sketch_plane", LineOwner.SKETCH_PLANE),
        ):
            with self.subTest(value):
                element = L0Element.from_dict(
                    _row(line_owner_kind=value, line_owner_id="4242"))
                self.assertIs(element.line_owner_kind, expected)
                self.assertEqual(element.line_owner_id, "4242")

    def test_the_field_is_orthogonal_to_geometry(self) -> None:
        # 9 256 из 9 407 линий несут КРИВУЮ, а не габарит: проверять
        # принадлежность только на габаритной строке значило бы мерить
        # меньшинство (1.6%) и звать это категорией.
        element = L0Element.from_dict(_row(
            geom_kind="curve", p0_mm=[0.0, 0.0, 0.0], p1_mm=[1000.0, 0.0, 0.0],
            bbox_min_mm=None, bbox_max_mm=None,
            line_owner_kind="sketch_plane", line_owner_id="4242"))
        self.assertIs(element.line_owner_kind, LineOwner.SKETCH_PLANE)
        self.assertEqual(element.line_owner_id, "4242")

    def test_read_failure_is_its_own_state(self) -> None:
        element = L0Element.from_dict(_row(line_owner_kind="read_failed"))
        self.assertIs(element.line_owner_kind, LineOwner.READ_FAILED)
        self.assertIsNone(element.line_owner_id)


class TheContractCanActuallyRefuse(unittest.TestCase):
    """Контроль-FAIL: без него зелёный цвет выше не сообщает ничего."""

    def test_an_owner_without_its_id_is_refused(self) -> None:
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(
                _row(line_owner_kind="view", line_owner_id=None))

    def test_an_id_without_its_owner_is_refused(self) -> None:
        # Идентификатор, чьё происхождение не записано, — не измерение.
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(_row(line_owner_id="4242"))

    def test_an_unknown_value_is_refused_not_coerced(self) -> None:
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(_row(line_owner_kind="model"))

    def test_a_refusal_state_must_not_carry_an_owner_id(self) -> None:
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(
                _row(line_owner_kind="none", line_owner_id="4242"))


class TheEmittedReaderAsksTheRightMembers(unittest.TestCase):
    """Текст C#: спрашивается вид, потом плоскость, и отказ типизирован.

    Проверка идёт по ОПРЕДЕЛЕНИЮ (что написано в эмитируемом теле), а не по
    соглашению об именах: канон, форма 7.
    """

    def test_the_helper_reads_view_before_sketch_plane(self) -> None:
        body = GEOMETRY_HELPER_CS
        self.assertIn("OwnerViewId", body)
        self.assertIn("SketchPlane", body)
        self.assertLess(
            body.index("OwnerViewId"), body.index("__ce.SketchPlane"),
            "вид спрашивается первым: у линии детализации плоскости может не "
            "быть вовсе, а у модельной линии вида нет по построению")

    def test_every_state_of_the_enum_is_emitted(self) -> None:
        for member in LineOwner:
            with self.subTest(member.value):
                self.assertIn(f'"{member.value}"', GEOMETRY_HELPER_CS)

    def test_the_reader_is_guarded_as_a_curve_element(self) -> None:
        # Без этого приведения ключ появился бы у КАЖДОГО элемента модели, и
        # «не снималось» перестало бы отличаться от «это не линия».
        self.assertIn("as CurveElement", GEOMETRY_HELPER_CS)

    def test_a_failed_read_is_named_rather_than_swallowed(self) -> None:
        self.assertIn('catch { __row["line_owner_kind"] = "read_failed"; }',
                      GEOMETRY_HELPER_CS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
