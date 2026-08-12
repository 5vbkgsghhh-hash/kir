"""Сухой гейт обязан компилировать ТО ЖЕ, что поедет в модель.

ОПРОВЕРГАЮЩИЙ ЗАМЕР 10.08.2026, настоящее здание, не гипотеза.
``tools/compile_gate_offline.py`` на ``snowdon_plumb_v3`` — том самом образце
Autodesk, который 30.07 живьём собрался 318 программами из 318, — дал
**0 из 156** программо-версий: все 26 программ отказали ``KIR-G104
piping_system_types: пусто в модели`` на каждой из шести версий. То есть
сильнейший офлайновый прибор проекта НИ РАЗУ не скомпилировал ни одного
инженерного здания и рапортовал об этом как об отказе программы.

Отказ сообщал не о программе, а о слепоте самого гейта, и слепота двойная:

1. **Лифт кормили не всеми боковыми индексами.** ``emit_all`` передавал
   ``sketch``/``family_placement``/``curve``/``curtain`` и молчал про
   ``mep_system``, ``annotation`` и ``tag`` — при том, что и живой конвейер,
   и ``tools/relift_offline.py`` передают все семь. Замер на
   ``snowdon_plumb_v3``: без индекса систем 6 343 опа и НИ ОДНОГО с
   ``system_type``; с ним 6 369 опов, из них 3 055 ``create_pipe`` и 181
   ``create_duct`` несут системный тип по имени. Прибор мерил компилятор на
   деградированном представлении — ровно та причина, по которой индекс марок
   в ``relift_offline`` снабжён отдельным комментарием.

2. **Снимок заземления собирался ЗАНОВО из L0 вместо захваченного каталога.**
   ``snapshot_from_l0`` восстанавливает пулы из распределения
   ``type_id``/``type_name`` элементов, а системный тип НЕ ЭЛЕМЕНТ L0 —
   такого пула из L0 не собрать в принципе. Рядом с каждым разбором лежит
   ``open_model.profile.json``, снятый тем же прогоном, и его уже читает
   ОБЩАЯ функция ``serving.source_catalogue_snapshot``, заведённая 28.07
   (``0bdb0cef``) ровно против этого класса: «отказ сообщал не о программе, а
   о слепоте вызывающего», замер тогда — 43 компилируемых опа из 543 против
   543. Третья по счёту частная копия того же знания и завела дефект в
   третий раз. Каталог есть у 69 из 76 разборов на этой машине.

Фикстура здесь СИНТЕТИЧЕСКАЯ намеренно: настоящий корпус разборов лежит вне
любого чекаута (машинно-локальные 4.1 ГБ), а тест обязан падать в чистом
клоне. Она воспроизводит ровно ту форму, на которой замер сделан: две трубы,
ДВА системных типа в каталоге (один — и умолчание вывелось бы, дефект бы не
проявился) и боковой индекс, называющий системный тип поимённо.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from tools.compile_gate_offline import emit_all, gate_snapshot

_LEVEL_ID = "355"
_PIPE_TYPE_ID = 604023
#: Их ДВА намеренно: при единственном варианте `ground` вывел бы системный
#: тип сам, и обе половины дефекта остались бы невидимыми.
_SYSTEM_TYPES = ((712045, "Hydronic Supply"), (712047, "Sanitary"))


def _pipe(element_id: str, y: float) -> dict:
    return {
        "record": "element",
        "element": {
            "element_id": element_id,
            "category": "OST_PipeCurves",
            "category_ru": "Трубы",
            "type_id": str(_PIPE_TYPE_ID),
            "type_name": "По умолчанию",
            "level_id": _LEVEL_ID,
            "level_name": "Уровень 1",
            "geom_kind": "curve",
            "p0_mm": [0.0, y, 2700.0],
            "p1_mm": [5000.0, y, 2700.0],
            "rotation_deg": None,
            "bbox_min_mm": [0.0, y - 50.0, 2650.0],
            "bbox_max_mm": [5000.0, y + 50.0, 2750.0],
            "host_id": None,
            "params": {"RBS_PIPE_DIAMETER_PARAM": 100},
        },
    }


def _pool(name: str, entries: tuple[tuple[int, str], ...]) -> dict:
    return {
        "name": name,
        "captured_count": len(entries),
        "complete": True,
        "entries": [
            {"element_id": element_id, "name": name_, "category": None,
             "class_name": None, "family_name": None, "type_name": None,
             "identity_exact": True, "p0_mm": None, "p1_mm": None,
             "params": None}
            for element_id, name_ in entries
        ],
    }


def _write_fixture(directory: pathlib.Path) -> None:
    header = {
        "record": "header",
        "schema_version": "1.0",
        "document": {
            "change_stamp": "offline-gate-fixture",
            "doc_name": "Инженерная фикстура",
            "grids": [],
            "levels": [{"elevation_mm": 0.0, "id": _LEVEL_ID,
                        "name": "Уровень 1"}],
            "project_info": {"address": None, "building_type_hint": None,
                             "name": "Фикстура"},
            "revit_version": "2026",
            "rooms": [],
            "units": "mm",
        },
    }
    rows = [header, _pipe("21201143", 0.0), _pipe("21201854", 3000.0),
            {"record": "footer", "category_count": 1, "element_count": 2,
             "link_count": 0, "stream_complete": True}]
    (directory / "L0.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")

    # Каталог модели-источника — тот самый, что снимает живой прогон.
    (directory / "open_model.profile.json").write_text(json.dumps({
        "schema_version": "kir-open-model-profile/1",
        "revit_version": "2026",
        "pools": [
            _pool("levels", ((int(_LEVEL_ID), "Уровень 1"),)),
            _pool("pipe_types", ((_PIPE_TYPE_ID, "По умолчанию"),)),
            _pool("piping_system_types", _SYSTEM_TYPES),
        ],
    }, ensure_ascii=False), encoding="utf-8")

    # Боковой индекс системного типа: без него труба поднимается без
    # `system_type`, и заземление честно отказывает KIR-G102.
    (directory / "mep_system.index.json").write_text(json.dumps({
        "schema_version": "kir-decompile-mep-system-index/1",
        "system_index": {
            "21201143": {"element_id": "21201143",
                         "system_type_id": str(_SYSTEM_TYPES[1][0]),
                         "system_type_name": _SYSTEM_TYPES[1][1]},
            "21201854": {"element_id": "21201854",
                         "system_type_id": str(_SYSTEM_TYPES[0][0]),
                         "system_type_name": _SYSTEM_TYPES[0][1]},
        },
        "failures": [],
    }, ensure_ascii=False), encoding="utf-8")


class OfflineGateGrounding(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = pathlib.Path(self._tmp.name)
        _write_fixture(self.directory)
        self.addCleanup(self._tmp.cleanup)

    def test_snapshot_is_the_captured_catalogue_not_a_reconstruction(self):
        """Пул системных типов из L0 НЕ СОБРАТЬ: это не элементы модели.

        Пока гейт восстанавливал снимок сам, `piping_system_types` в нём не
        было вовсе, и любая инженерная программа отказывала KIR-G104 «пусто в
        модели» — прибор сообщал о собственной слепоте.
        """
        snapshot, source = gate_snapshot(self.directory)
        self.assertEqual(source, "open_model.profile.json")
        self.assertIn("piping_system_types", snapshot)
        self.assertEqual(
            sorted(row["name"] for row in snapshot["piping_system_types"]),
            sorted(name for _, name in _SYSTEM_TYPES))
        # Уровни обязаны остаться: заземление уровня — обязательное.
        self.assertTrue(snapshot.get("levels"))

    def test_lift_gets_every_side_index_the_live_pipeline_gets(self):
        """Гейт обязан кормить лифт тем же набором индексов, что живой ход.

        Иначе он мерит компилятор на деградированном представлении: труба
        поднимается без системного типа, и отказ выглядит дефектом языка.
        """
        _, stats = emit_all(self.directory, chunk=250)
        self.assertEqual(stats["ops"], 2, stats)
        self.assertEqual(stats["named_system_type_ops"], 2, stats)

    def test_a_piping_building_compiles_on_all_six_versions(self):
        """Сквозное утверждение, ради которого гейт существует."""
        emitted, stats = emit_all(self.directory, chunk=250)
        self.assertEqual(stats["refused"], {}, stats)
        self.assertEqual(len(emitted), 6 * stats["programs"], stats)
        self.assertTrue(stats["compiler_ready"], stats)
        self.assertEqual(stats["snapshot_source"], "open_model.profile.json")

    def test_a_run_without_the_catalogue_says_so_instead_of_pretending(self):
        """Разбор без каталога — не повод подделать пул.

        `демо-v3`, единственное здание, на котором гейт когда-либо давал
        чистый прогон, каталога не имеет вовсе. Восстановление из L0 остаётся
        запасным путём, но обязано быть НАЗВАНО: молчаливая подмена сделала бы
        число гейта несравнимым между зданиями.
        """
        (self.directory / "open_model.profile.json").unlink()
        snapshot, source = gate_snapshot(self.directory)
        self.assertEqual(source, "L0 (каталога нет)")
        self.assertNotIn("piping_system_types", snapshot)
        _, stats = emit_all(self.directory, chunk=250)
        self.assertEqual(stats["snapshot_source"], "L0 (каталога нет)")


if __name__ == "__main__":
    unittest.main()
