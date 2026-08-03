"""Захват потолка и ограждения стадией ``sketch`` (wave/capture, 2026-07-29).

ПОЧЕМУ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ. 29.07 в реестр приехали ``create_ceiling`` и
``create_railing`` — ворота 6/6 зелёные, а покрытие не сдвинулось ни на одном
здании. Причина не в операциях, а в том, что поднимать НЕЧЕГО: на слепке
рабочей документации (13A-RD-AR-K2, 55 293 элемента) все 81 потолок лежат
``bbox_only`` с пустым ``params``, все 203 ограждения — ``bbox_only``/``point``,
и ни один из них не встречается ни в ``sketch.index.json``, ни в
``curve.index.json``. Операция есть — исходных данных нет.

Тесты ниже написаны ДО правки и падали на ней красным: они называют ровно тот
захват, которого не было. Порядок утверждений — от «стадия вообще смотрит на
категорию» до «нечитаемое поле уходит типизированным отказом, а не умолчанием».

ГРАНИЦА, КОТОРУЮ ЭТОТ ФАЙЛ НЕ ПЕРЕХОДИТ. Позиция установки ограждения
(``RailingPlacementPosition``) здесь не проверяется, потому что снять её
НЕЧЕМ: полный член-состав ``Autodesk.Revit.DB.Architecture.Railing`` на всех
шести версиях — 20 членов, и ``RailingPlacementPosition`` встречается ТОЛЬКО
как параметр двух перегрузок ``Create`` и как три поля собственного
перечисления. Геттера не существует. Поэтому отказ ``_lift_railing`` по
позиции — законный и остаётся; закрывается он не захватом, а тем, что
путевая перегрузка ``Railing.Create(doc, CurveLoop, typeId, baseLevelId)``
позиции не требует вовсе.
"""

from __future__ import annotations

import unittest

from kukai.ir.decompile.pipeline import _STAGE_CATEGORIES
from kukai.ir.decompile.sketch_extract import (
    SKETCH_EXTRACT_SCHEMA_VERSION,
    SketchPayloadError,
    build_sketch_extract_cs,
    extract_sketch_profiles,
)


def _loop(points: list[list[float]]) -> dict:
    count = len(points)
    return {
        "points_mm": points,
        "curve_kinds": ["line"] * count,
        "arc_midpoints_mm": [None] * count,
    }


RECTANGLE = _loop([[0, 0], [6000, 0], [6000, 4000], [0, 4000]])


def _element(
    element_id: str,
    *,
    category: str,
    loops: list[dict] | None = None,
    available: bool = False,
    reason: str | None = None,
    stairs_run_paths: list[dict] | None = None,
    railing: dict | None = None,
) -> dict:
    row: dict = {
        "element_id": element_id,
        "category": category,
        "profile_available": available,
        "loops": loops if loops is not None else [],
        "reason": reason,
        "stairs_run_paths": (
            stairs_run_paths if stairs_run_paths is not None else []),
    }
    if railing is not None:
        row["railing"] = railing
    return row


def _payload(*elements: dict) -> dict:
    return {
        "schema_version": SKETCH_EXTRACT_SCHEMA_VERSION,
        "elements": list(elements),
    }


#: Дословно то, что пишет эмиттер: строка недоступного профиля ОБЯЗАНА нести
#: непустую причину, и у ограждения она всегда одна и та же.
RAILING_NO_PROFILE = (
    "railing is a path element and has no closed Sketch profile")


def _railing_element(element_id: str, **kwargs) -> dict:
    return _element(
        element_id,
        category=kwargs.pop("category", "OST_StairsRailing"),
        reason=kwargs.pop("reason", RAILING_NO_PROFILE),
        **kwargs,
    )


def _railing(
    *,
    path_available: bool = True,
    points: list[list[float]] | None = None,
    plane_z_mm: float | None = 141380.0,
    path_reason: str | None = None,
    host_available: bool = True,
    has_host: bool | None = False,
    host_id: str | None = None,
    host_reason: str | None = None,
    base_available: bool = True,
    base_level_id: str | None = "11835839",
    base_reason: str | None = None,
) -> dict:
    pts = points if points is not None else [[0, 0], [4000, 0], [4000, 2500]]
    return {
        "path": {
            "available": path_available,
            "points_mm": pts if path_available else [],
            # Открытая цепь: N точек ⇒ N-1 кривых.
            "curve_kinds": ["line"] * (len(pts) - 1) if path_available else [],
            "arc_midpoints_mm": (
                [None] * (len(pts) - 1) if path_available else []),
            "plane_z_mm": plane_z_mm if path_available else None,
            "reason": path_reason,
        },
        "host": {
            "available": host_available,
            "has_host": has_host if host_available else None,
            "host_id": host_id if host_available else None,
            "reason": host_reason,
        },
        "base_level": {
            "available": base_available,
            "level_id": base_level_id if base_available else None,
            "reason": base_reason,
        },
    }


class CeilingCaptureTests(unittest.TestCase):
    """Потолок — тот же эскизный элемент, что пол и кровля."""

    def test_sketch_stage_selects_ceilings(self) -> None:
        # Без этой строки конвейер никогда не отправит id потолка на стадию,
        # и сколь угодно правильный C# останется мёртвым кодом.
        self.assertIn("OST_Ceilings", _STAGE_CATEGORIES["sketch"])

    def test_emitter_collects_ceilings(self) -> None:
        body = build_sketch_extract_cs(["101"])
        self.assertIn("OST_Ceilings", body)
        # Потолок обязан идти ТЕМ ЖЕ путём, что пол: единственный зависимый
        # Sketch. Отдельная ветка здесь означала бы вторую правду о профиле.
        self.assertIn("__ProfileRow(__ceiling, \"OST_Ceilings\")", body)

    def test_parser_accepts_a_ceiling_profile(self) -> None:
        extraction = extract_sketch_profiles(_payload(_element(
            "15972657",
            category="OST_Ceilings",
            loops=[RECTANGLE],
            available=True,
        )))
        row = extraction.profile_index["15972657"]
        self.assertTrue(row["profile_available"])
        self.assertEqual(row["exterior_loop"], [
            [0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0],
        ])
        self.assertEqual(row["holes"], [])

    def test_ceiling_with_a_courtyard_keeps_the_hole(self) -> None:
        courtyard = _loop([
            [2000, 1000], [4000, 1000], [4000, 3000], [2000, 3000]])
        extraction = extract_sketch_profiles(_payload(_element(
            "15972658",
            category="OST_Ceilings",
            loops=[courtyard, RECTANGLE],
            available=True,
        )))
        row = extraction.profile_index["15972658"]
        self.assertEqual(len(row["holes"]), 1)

    def test_unreadable_ceiling_profile_is_a_named_refusal(self) -> None:
        # Тихая потеря запрещена: непрочитанный профиль обязан назвать себя,
        # а не притвориться пустым контуром.
        extraction = extract_sketch_profiles(_payload(_element(
            "15972659",
            category="OST_Ceilings",
            available=False,
            reason="dependent Sketch count is 0",
        )))
        row = extraction.profile_index["15972659"]
        self.assertFalse(row["profile_available"])
        self.assertTrue(any(
            "dependent Sketch count is 0" in failure.reason
            for failure in extraction.failures))


class RailingCaptureTests(unittest.TestCase):
    """Ограждение: путь — открытая цепь, хозяин и базовый уровень — отдельно."""

    def test_sketch_stage_selects_railings(self) -> None:
        self.assertIn("OST_StairsRailing", _STAGE_CATEGORIES["sketch"])

    def test_emitter_collects_railings_via_getpath(self) -> None:
        body = build_sketch_extract_cs(["101"])
        self.assertIn("OST_StairsRailing", body)
        self.assertIn("GetPath()", body)
        # Путь ограждения — ОТКРЫТАЯ цепь. Замкни его — и первая же прямая
        # лестничная нитка станет «незамкнутым контуром» и уйдёт в отказ.
        self.assertIn("__ReadChain(__railCurves, false)", body)

    def test_parser_keeps_an_open_railing_path(self) -> None:
        extraction = extract_sketch_profiles(_payload(_railing_element("11842713", railing=_railing())))
        record = extraction.railing_path_index["11842713"]
        self.assertTrue(record["path_available"])
        self.assertEqual(record["points_mm"], [
            [0.0, 0.0], [4000.0, 0.0], [4000.0, 2500.0]])
        self.assertEqual(record["curve_kinds"], ["line", "line"])

    def test_railing_path_keeps_its_elevation(self) -> None:
        # Цепь плоская, но НЕ на нуле. Уронить Z молча — значит положить
        # ограждение 59-этажной башни на землю.
        extraction = extract_sketch_profiles(_payload(_railing_element(
            "11842713", railing=_railing(plane_z_mm=141380.0))))
        self.assertEqual(
            extraction.railing_path_index["11842713"]["plane_z_mm"], 141380.0)

    def test_railing_host_is_captured_separately_from_path(self) -> None:
        extraction = extract_sketch_profiles(_payload(_railing_element(
            "11842714", railing=_railing(has_host=True, host_id="777"))))
        record = extraction.railing_path_index["11842714"]
        self.assertTrue(record["has_host"])
        self.assertEqual(record["host_id"], "777")

    def test_railing_base_level_is_captured(self) -> None:
        extraction = extract_sketch_profiles(_payload(_railing_element(
            "11842715", railing=_railing(base_level_id="11835839"))))
        self.assertEqual(
            extraction.railing_path_index["11842715"]["base_level_id"],
            "11835839")

    def test_unreadable_path_refuses_and_does_not_default(self) -> None:
        extraction = extract_sketch_profiles(_payload(_railing_element(
            "11842716", railing=_railing(
                path_available=False,
                path_reason="Railing.GetPath failed: InapplicableDataException",
            ))))
        record = extraction.railing_path_index["11842716"]
        self.assertFalse(record["path_available"])
        self.assertEqual(record["points_mm"], [])
        self.assertTrue(any(
            "InapplicableDataException" in failure.reason
            for failure in extraction.failures))

    def test_each_optional_read_fails_on_its_own(self) -> None:
        # Хозяин не прочитался — путь всё равно обязан уцелеть. Общий try на
        # весь элемент — это ровно тот баг, что лишил помещения точки.
        extraction = extract_sketch_profiles(_payload(_railing_element(
            "11842717", railing=_railing(
                host_available=False,
                host_reason="Railing.HostId failed: InvalidOperationException",
            ))))
        record = extraction.railing_path_index["11842717"]
        self.assertTrue(record["path_available"])
        self.assertEqual(record["points_mm"], [
            [0.0, 0.0], [4000.0, 0.0], [4000.0, 2500.0]])
        self.assertIsNone(record["has_host"])
        self.assertTrue(any(
            "InvalidOperationException" in failure.reason
            for failure in extraction.failures))

    def test_unavailable_host_cannot_smuggle_a_value(self) -> None:
        broken = _railing()
        broken["host"] = {
            "available": False, "has_host": True, "host_id": "777",
            "reason": "unreadable",
        }
        with self.assertRaises(SketchPayloadError):
            extract_sketch_profiles(_payload(_railing_element("11842718", railing=broken)))

    def test_railing_cannot_claim_a_closed_profile(self) -> None:
        with self.assertRaises(SketchPayloadError):
            extract_sketch_profiles(_payload(_railing_element(
                "11842719", loops=[RECTANGLE], available=True,
                reason=None, railing=_railing())))


class FrozenFormatTests(unittest.TestCase):
    """Старый диалект обязан читаться ровно как раньше."""

    def test_floor_payload_without_the_new_field_still_parses(self) -> None:
        extraction = extract_sketch_profiles(_payload(_element(
            "101", category="OST_Floors", loops=[RECTANGLE], available=True)))
        self.assertTrue(extraction.profile_index["101"]["profile_available"])
        self.assertEqual(extraction.railing_path_index, {})

    def test_non_railing_cannot_carry_a_railing_block(self) -> None:
        with self.assertRaises(SketchPayloadError):
            extract_sketch_profiles(_payload(_element(
                "101", category="OST_Floors", loops=[RECTANGLE],
                available=True, railing=_railing())))

    def test_stage_category_prefix_is_untouched(self) -> None:
        # Формат возобновления заморожен: дописывать только в конец.
        # Пол/кровля/лестница обязаны остаться в стадии.
        for category in ("OST_Floors", "OST_Roofs", "OST_Stairs"):
            self.assertIn(category, _STAGE_CATEGORIES["sketch"])


class TheRefusalActuallyDisappears(unittest.TestCase):
    """Приёмочный сигнал волны, пройденный от формы ответа моста до лифта.

    Тесты выше проверяют захват по частям. Этот — единственный, который
    отвечает на вопрос задачи целиком: если мост ответит ровно тем, что
    печатает НАШ эмиттер, исчезнет ли причина «нет профиля эскиза потолка»?
    Промежуточные звенья тут настоящие: тот же ``extract_sketch_profiles``,
    тот же ``profile_index``, тот же ``lift_document_detailed``.

    ЧЕГО ЭТОТ ТЕСТ НЕ ДОКАЗЫВАЕТ: что живой Revit ответит именно так.
    Живого Revit у волны не было; доказано, что ответ такой ФОРМЫ проходит
    насквозь, и что C#, который её печатает, компилируется на шести версиях.
    """

    def _lift_with(self, payload: dict, category: str, element_id: str):
        import copy

        from kukai.ir.decompile.lift import lift_document_detailed
        from kukai.ir.decompile.schema import L0Document
        from kukai.ir.decompile.tests.fixtures_decompile import (
            make_element, project1_metadata)

        extraction = extract_sketch_profiles(payload)
        element = make_element(category, 4100, ordinal=0)
        element["element_id"] = element_id
        row = copy.deepcopy(project1_metadata())
        row["change_stamp"] = "capture-v1"
        row["elements"] = [element]
        row["category_status"] = []
        result = lift_document_detailed(
            L0Document.from_dict(row), extraction.profile_index)
        return {node["source_element_id"]: node
                for node in result.nodes}[element_id], extraction

    def test_a_captured_ceiling_stops_being_an_atom(self) -> None:
        # Ровно та строка, которую печатает __ProfileRow для потолка,
        # включая ключ slopes (эмиттер всегда его пишет).
        emitted = {
            "element_id": "15972657",
            "category": "OST_Ceilings",
            "profile_available": True,
            "loops": [RECTANGLE],
            "slopes": None,
            "reason": None,
            "stairs_run_paths": [],
        }
        node, _ = self._lift_with(
            _payload(emitted), "OST_Ceilings", "15972657")
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_ceiling")
        self.assertEqual(len(node["params"]["outline"]), 4)

    def test_the_same_ceiling_without_capture_is_still_an_atom(self) -> None:
        # Контроль: без захвата причина обязана остаться на месте, иначе
        # предыдущий тест доказывал бы не то, что мы думаем.
        node, _ = self._lift_with(
            _payload(), "OST_Ceilings", "15972657")
        self.assertEqual(node["kind"], "atom")

    def test_a_captured_railing_still_refuses_until_the_lift_reads_it(
            self) -> None:
        """ЧЕСТНАЯ ГРАНИЦА ВОЛНЫ, записанная тестом, а не только отчётом.

        Путь ограждения теперь СНЯТ и лежит в ``railing_path_index``. Но
        ``_lift_railing`` этого индекса не читает — он живёт в ``lift.py``,
        которым владеет соседняя волна, и трогать его здесь нельзя. Поэтому
        ограждения по-прежнему НЕ ПОДНИМАЮТСЯ, и утверждать обратное было бы
        враньём. Тест зафиксирует ровно тот день, когда лифт научится.
        """
        node, extraction = self._lift_with(
            _payload(_railing_element("11842713", railing=_railing())),
            "OST_StairsRailing", "11842713")
        # Захват состоялся…
        self.assertTrue(
            extraction.railing_path_index["11842713"]["path_available"])
        # …а подъём — нет, и причина по-прежнему называет геометрию.
        self.assertEqual(node["kind"], "atom")


if __name__ == "__main__":
    unittest.main()
