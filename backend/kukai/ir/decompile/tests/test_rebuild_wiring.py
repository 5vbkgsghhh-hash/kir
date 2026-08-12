"""Провод `rebuild` в живую пересборку: с базой — дельта, без базы — как было.

Слой `rebuild` пролежал на складе 362 строками и 14 тестами, и все 14 проверяли
ЧТО он считает: T-APPLY, порядок, отказ на чужом состоянии.  Ни один не
проверял, доходит ли до него хоть один живой вход, — поэтому склад и не был
виден изнутри тестов.  Этот файл проверяет ровно второе, и только его.

Три закона:

* **инертность** — без `base_doc_stamp` пересборка обязана дать ТЕ ЖЕ чанки и
  те же опы, что и до этой волны.  Не «примерно те же»: пересборка целого
  здания — это то, что уже работало, и новый слой не имеет права её сдвинуть;
* **громкий отказ вместо тихой полноты** — база названа, а дельту посчитать
  нельзя (флаг выключен, базы нет на диске, дельта не применяется): ответ
  обязан быть типизованным отказом.  Молчаливый откат к полной пересборке
  здесь хуже отказа: оператор просил дельту и получил бы вдвое больше опов,
  ничего об этом не узнав;
* **замыкание по ссылкам** — изменившийся хостируемый оп обязан тянуть за
  собой хозяина.  Без этого материализатор снимает его типизованным пропуском
  `host_unmaterialized`, и дельта МОЛЧА не строит ровно то, что правили.  Это
  и есть опровергающий тест волны: он падает на дельте без замыкания.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import pathlib
import tempfile
import unittest
from typing import Any
from unittest import mock

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_rebuild_wiring_queue.jsonl"))

from kukai.ir import serving  # noqa: E402
from kukai.ir.decompile.fold import fold_document, iter_l1_leaves  # noqa: E402
from kukai.ir.decompile.lift import lift_document  # noqa: E402
from kukai.ir.decompile.materialize import leaves_to_program  # noqa: E402
from kukai.ir.decompile.rebuild import rebuild_enabled  # noqa: E402
from kukai.ir.decompile.rebuild_plan import (  # noqa: E402
    REBUILD_PLAN_SCHEMA,
    delta_rebuild_plan,
    plan_refusal,
    plan_report,
)
from kukai.ir.decompile.tests.fixtures_decompile import (  # noqa: E402
    make_element,
)
from kukai.ir.decompile.tests.test_merkle import (  # noqa: E402
    _document,
    _fold,
    _grid_building,
)

_FLAG = "KUKAI_IR_REBUILD"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _ShimLLM:
    _revit_version = "2026"

    async def _repair_code(self, *a: Any, **k: Any) -> None:
        return None


async def _never_bridge(method: str, params: dict) -> dict:  # pragma: no cover
    raise AssertionError("мост не смеет вызываться в сухом прогоне")


def _hosted_document(*, door_dx: float = 0.0, name: str = "hosted"):
    """Стена 9001 и дверь 31002 на ней — `make_element` шьёт host_id='9001'.

    Правится ПОЛОЖЕНИЕ двери, а не её ширина: `FAMILY_WIDTH_PARAM` лифтер в
    L1 не переносит (у `create_door` остаются `host`/`offset_mm`/`symbol`), и
    правка ширины дала бы два одинаковых дерева — тест проверял бы пустую
    дельту, думая, что проверяет замыкание.
    """

    wall = make_element("OST_Walls", 9001, ordinal=0)
    door = make_element("OST_Doors", 31_002, ordinal=0)
    door["p0_mm"] = [door["p0_mm"][0] + door_dx,
                     door["p0_mm"][1], door["p0_mm"][2]]
    level = ("100", "Этаж 1", 0.0)
    return _document([level], [wall, door], name=name)


def _hosted_tree(*, door_dx: float = 0.0):
    document = _hosted_document(door_dx=door_dx)
    return fold_document(document, lift_document(document))


def _source_id_of(tree, category_substring: str) -> str:
    for leaf in iter_l1_leaves(tree):
        name = str(leaf.get("op_name") or leaf.get("category"))
        if category_substring in name:
            return leaf["source_element_id"]
    raise AssertionError(f"в дереве нет листа {category_substring!r}")


class RefClosure(unittest.TestCase):
    """Опровергающий тест волны: без замыкания дельта теряет правку."""

    def test_a_changed_door_drags_its_unchanged_wall_into_the_delta(
            self) -> None:
        tree_a = _hosted_tree(door_dx=0.0)
        tree_b = _hosted_tree(door_dx=1_500.0)
        plan = delta_rebuild_plan(tree_a, tree_b)

        door_id = _source_id_of(tree_b, "door")
        wall_id = _source_id_of(tree_b, "wall")
        self.assertIn(door_id, plan.emit_source_ids,
                      "дверь правили — она обязана быть в дельте")
        self.assertNotIn(wall_id, plan.emit_source_ids,
                         "стену не трогали — дельта не смеет звать её сама")
        self.assertIn(
            wall_id, plan.closure_source_ids,
            "хозяин не втянут замыканием — материализатор снимет дверь "
            "пропуском host_unmaterialized, и дельта промолчит о правке")

    def test_without_the_wall_the_materializer_silently_drops_the_door(
            self) -> None:
        """Ровно тот молчаливый провал, ради которого замыкание и введено."""

        tree_b = _hosted_tree(door_dx=1_500.0)
        door_id = _source_id_of(tree_b, "door")
        only_door = [
            leaf for leaf in iter_l1_leaves(tree_b)
            if leaf["source_element_id"] == door_id]

        naive = leaves_to_program(only_door)
        self.assertEqual(
            sum(len(program["ops"]) for program in naive.programs), 0,
            "наивная дельта построила бы дверь без стены — тогда замыкание "
            "не нужно, и этот тест обязан упасть первым")
        self.assertTrue(
            any("host_unmaterialized" in record.reason
                for record in naive.skipped),
            "дверь исчезла без типизованного пропуска — это уже другой дефект")

        # А с замыканием — строится.
        plan = delta_rebuild_plan(_hosted_tree(door_dx=0.0), tree_b)
        with_wall = leaves_to_program([
            leaf for leaf in iter_l1_leaves(tree_b)
            if leaf["source_element_id"] in plan.materialize_source_ids])
        self.assertGreater(
            sum(len(program["ops"]) for program in with_wall.programs), 0)

    def test_closure_keeps_the_transition_theorem(self) -> None:
        """T-APPLY на РАСШИРЕННОЙ программе — замыкание не ломает теорему.

        `delta_rebuild_plan` прогоняет `assert_transition` внутри, поэтому
        достаточно, чтобы он не поднял; но проверить пару «снять X/поставить X»
        явно стоит: она и есть причина, по которой замыкание безопасно.
        """

        plan = delta_rebuild_plan(
            _hosted_tree(door_dx=0.0), _hosted_tree(door_dx=1_500.0))
        refresh = [op for op in plan.program.ops if op.reason == "refresh"]
        self.assertTrue(refresh, "замыкание было, а компенсации в дельте нет")
        removed = sorted(
            op.remove_ops[0] for op in refresh if op.kind == "retire")
        added = sorted(op.add_ops[0] for op in refresh if op.kind == "emit")
        self.assertEqual(removed, added,
                         "компенсация несимметрична — на мультимножестве это "
                         "уже не ноль, и T-APPLY держится случайно")


class PlanShape(unittest.TestCase):
    def test_flag_is_off_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FLAG, None)
            self.assertFalse(rebuild_enabled())

    def test_a_building_against_itself_is_an_empty_delta(self) -> None:
        tree = _fold(_grid_building(floors=3))
        plan = delta_rebuild_plan(tree, copy.deepcopy(tree))
        self.assertTrue(plan.is_empty)
        report = plan_report(plan)
        self.assertTrue(report["identical"])
        self.assertEqual(report["delta_leaves"], 0)
        self.assertEqual(report["full_leaves"], report["leaves_b"])

    def test_a_local_edit_costs_less_than_the_whole_building(self) -> None:
        tree_a = _fold(_grid_building(floors=3))
        tree_b = _fold(_grid_building(floors=3, extra_furniture_on_floor=1))
        report = plan_report(delta_rebuild_plan(tree_a, tree_b))
        self.assertLess(report["delta_leaves"], report["full_leaves"])
        self.assertGreater(report["reused_leaves"], report["delta_leaves"])

    def test_a_refusal_is_not_an_empty_delta(self) -> None:
        report = plan_refusal(ValueError("дерево-огрызок"))
        self.assertFalse(report["ok"])
        self.assertEqual(report["schema"], REBUILD_PLAN_SCHEMA)
        self.assertNotIn("delta_leaves", report)
        self.assertTrue(report["error"]["message"].strip())


class ServingWiring(unittest.TestCase):
    """Живой вход: `handle_revit_rebuild` ← `api/admin_kir.py::rebuild`."""

    def setUp(self) -> None:
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        os.environ.pop("KUKAI_IR_ATOM_ESCROW", None)
        self._dev = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._dev.start()
        self._tmp = tempfile.TemporaryDirectory()
        self._dirs: dict[str, str] = {}

    def tearDown(self) -> None:
        self._dev.stop()
        self._tmp.cleanup()
        os.environ.pop("KUKAI_KIR_DECOMPILE", None)
        os.environ.pop(_FLAG, None)

    def _persist(self, stamp: str, tree) -> None:
        directory = pathlib.Path(self._tmp.name) / stamp
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tree.json").write_text(
            json.dumps(tree), encoding="utf-8")
        self._dirs[stamp] = str(directory)

    def _out_dir(self, stamp: str) -> str:
        return self._dirs.get(stamp, str(pathlib.Path(self._tmp.name) / stamp))

    def _rebuild(self, args: dict) -> dict:
        with mock.patch.object(serving, "_decompile_out_dir", self._out_dir):
            return _run(serving.handle_revit_rebuild(
                {"dry_run": True, **args}, _ShimLLM(), _never_bridge))

    def test_without_a_base_the_summary_says_so_and_nothing_moves(
            self) -> None:
        """Инертность: ключ есть всегда, `null` значит «здание целиком»."""

        self._persist("target", _fold(_grid_building(floors=2)))
        result = self._rebuild({"doc_stamp": "target"})
        self.assertTrue(result["ok"], msg=result)
        self.assertIn("delta", result)
        self.assertIsNone(result["delta"],
                          "без базы дельты быть не может — иначе пересборка "
                          "молча стала частичной")
        self.assertGreater(result["chunks_total"], 0)

    def test_switching_the_flag_moves_no_chunk_of_a_baseless_rebuild(
            self) -> None:
        self._persist("target", _fold(_grid_building(floors=2)))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FLAG, None)
            off = self._rebuild({"doc_stamp": "target"})
        with mock.patch.dict(os.environ, {_FLAG: "1"}):
            on = self._rebuild({"doc_stamp": "target"})
        self.assertEqual(off["chunks_total"], on["chunks_total"])
        self.assertEqual(off["chunks_ok"], on["chunks_ok"])
        self.assertIsNone(off["delta"])
        self.assertIsNone(on["delta"])

    def test_a_named_base_with_the_flag_off_is_refused_by_name(self) -> None:
        """Громкий отказ вместо тихой полной пересборки."""

        self._persist("target", _fold(_grid_building(floors=2)))
        self._persist("base", _fold(_grid_building(floors=2)))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FLAG, None)
            result = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "base"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "rebuild_delta_disabled")
        self.assertNotIn("chunks_total", result,
                         "отказ протащил за собой полную пересборку — ровно "
                         "того молчаливого отката тут и не должно быть")

    def test_a_missing_base_is_refused_not_treated_as_no_difference(
            self) -> None:
        self._persist("target", _fold(_grid_building(floors=2)))
        with mock.patch.dict(os.environ, {_FLAG: "1"}):
            result = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "нет-такого"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_base_decompile")

    def test_a_malformed_base_is_refused_not_silently_rebuilt_whole(
            self) -> None:
        self._persist("target", _fold(_grid_building(floors=2)))
        directory = pathlib.Path(self._tmp.name) / "огрызок"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tree.json").write_text(
            json.dumps({"kind": "building"}), encoding="utf-8")
        self._dirs["огрызок"] = str(directory)
        with mock.patch.dict(os.environ, {_FLAG: "1"}):
            result = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "огрызок"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "delta_not_applicable")
        self.assertNotIn("chunks_total", result)

    def test_an_identical_base_leaves_nothing_to_build(self) -> None:
        tree = _fold(_grid_building(floors=2))
        self._persist("target", tree)
        self._persist("base", copy.deepcopy(tree))
        with mock.patch.dict(os.environ, {_FLAG: "1"}):
            result = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "base"})
        self.assertTrue(result["ok"], msg=result)
        self.assertEqual(result["chunks_total"], 0,
                         "здания совпали, а пересборка всё равно что-то "
                         "строит — дельта не подключена")
        self.assertTrue(result["delta"]["identical"])
        self.assertEqual(result["delta"]["delta_leaves"], 0)

    def test_a_local_edit_builds_fewer_ops_than_the_whole_building(
            self) -> None:
        """Собственно ради чего всё: правка этажа стоит меньше здания."""

        self._persist("base", _fold(_grid_building(floors=3)))
        self._persist(
            "target",
            _fold(_grid_building(floors=3, extra_furniture_on_floor=1)))
        full = self._rebuild({"doc_stamp": "target"})
        with mock.patch.dict(os.environ, {_FLAG: "1"}):
            delta = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "base"})
        self.assertTrue(full["ok"], msg=full)
        self.assertTrue(delta["ok"], msg=delta)
        self.assertLess(delta["delta"]["delta_leaves"],
                        delta["delta"]["full_leaves"])
        self.assertLessEqual(delta["chunks_total"], full["chunks_total"])
        # Отчёт обязан НАЗЫВАТЬ то, чего дельта не делает: снятие старых
        # элементов и недоказуемое офлайн условие про содержимое документа.
        self.assertTrue(delta["delta"]["retire_not_executed"])
        self.assertIn("base", delta["delta"]["precondition_ru"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
