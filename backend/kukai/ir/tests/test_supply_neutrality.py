"""§18.5 — закон нейтральности поставки. Опровергающие тесты (§18.7 п.2).

Написаны ДО починки и на момент написания падали все: в исполняемом коде
компилятора стояли литеральный id устройства владельца (`serving.ADMIN_DEVICE`),
абсолютный путь установки для телеметрии отказов (`coverage_feed._DEFAULT`) и
абсолютный `/root/...` для вывода декомпайла (`extract.DEFAULT_OUTPUT_ROOT`).

Что именно утверждается:
  * список допущенных устройств принадлежит УСТАНОВКЕ (env KUKAI_ADMIN_DEVICES),
    а не автору кода; env задан и пуст ⇒ живой путь выключен;
  * отказ гейта НАЗЫВАЕТ переменную, которую надо настроить (иначе сторонний
    разработчик не может открыть обратный путь никогда);
  * отсутствие пути = функция выключена, а не запись в чужую ФС;
  * дефолтный корень вывода не указывает в чужую установку.
"""
from __future__ import annotations

import asyncio
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from kukai.ir import coverage_feed, serving
from kukai.ir.decompile import extract
from kukai.ir.tests.gate_fixture import enter_kir_mode


def _run(coro):
    return asyncio.run(coro)


class _EnvGuard(unittest.TestCase):
    """Снимает/возвращает env-переменные, которые тест трогает."""

    _VARS: tuple[str, ...] = ()

    def setUp(self) -> None:
        self._saved = {name: os.environ.get(name) for name in self._VARS}

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class AdminDeviceAllowList(_EnvGuard):
    _VARS = ("KUKAI_ADMIN_DEVICES", "KUKAI_KIR_TOOL", "KUKAI_KIR_DECOMPILE")

    def test_env_list_is_parsed_and_trimmed(self) -> None:
        os.environ["KUKAI_ADMIN_DEVICES"] = " dev-a , dev-b ,,"
        self.assertEqual(serving.admin_devices(), ("dev-a", "dev-b"))
        self.assertTrue(serving.is_admin_device("dev-a"))
        self.assertTrue(serving.is_admin_device("dev-b"))
        self.assertFalse(serving.is_admin_device("dev-c"))
        self.assertFalse(serving.is_admin_device(None))

    def test_env_present_but_empty_disables_the_live_path(self) -> None:
        """РЕЖИМ СТАВИТСЯ ЗДЕСЬ НАРОЧНО, И ЭТО УСИЛЕНИЕ, А НЕ ПОСЛАБЛЕНИЕ.

        Предмет теста — ПУСТОЙ СПИСОК устройств. С 13.08 гейт имеет третье
        условие, и без режима `revit_ir_enabled()` ложен по ДВУМ причинам
        сразу — то есть зелёный получен без акта различения: тест прошёл бы и
        при полностью сломанной проверке устройств. Включив режим, оставляем
        ровно одну возможную причину отказа, ту самую, ради которой тест
        написан.
        """
        enter_kir_mode(self)
        os.environ["KUKAI_ADMIN_DEVICES"] = "   "
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        self.assertEqual(serving.admin_devices(), ())
        with mock.patch.object(serving, "_turn_device_id",
                               return_value="any-device"):
            self.assertFalse(serving.revit_ir_enabled())
            self.assertFalse(serving.revit_decompile_enabled())

    def test_unset_env_is_the_same_as_empty_and_never_guesses_a_device(self):
        """НЕЗАДАННАЯ ПЕРЕМЕННАЯ И ЗАДАННАЯ ПУСТОЙ — ОДНО И ТО ЖЕ.

        Прежняя редакция называлась «unset keeps this installation working» и
        требовала, чтобы `admin_devices()` вернул `_MIGRATION_ADMIN_DEVICE` —
        id ЭТОЙ машины, зашитый литералом в файл, который публикуется
        отдельным репозиторием. 15.08.2026 волна границы опенсорса литерал
        сняла, и фолбэка не стало: `admin_devices` документирует это дословно
        («угадывать чужое устройство мы не вправе»).

        🔴 ТЕСТ ПЕРЕПИСАН ПОД ДОСТИГНУТОЕ, А НЕ ПОДОГНАН ПОД КРАСНЫЙ. Разница
        проверяемая: прежнее ожидание требовало ПРИСУТСТВИЯ литерала, новое
        требует его ОТСУТСТВИЯ, и соседний тест ниже это принуждает. Замысел
        сохранён и усилен — «в компиляторе нет ничьего устройства», — тогда
        как подгонка ослабила бы его до «как получилось».

        Режим ставится явно по тому же доводу, что и в тесте выше: без него
        `revit_ir_enabled()` ложен по двум причинам сразу, и зелёный пришёл бы
        без акта различения.
        """
        enter_kir_mode(self)
        os.environ.pop("KUKAI_ADMIN_DEVICES", None)
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self.assertEqual(serving.admin_devices(), ())
        with mock.patch.object(serving, "_turn_device_id",
                               return_value="any-device"):
            self.assertFalse(serving.revit_ir_enabled())

    def test_gate_refusal_names_the_env_variable(self) -> None:
        os.environ["KUKAI_ADMIN_DEVICES"] = ""
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"

        async def _never_bridge(method, params):  # pragma: no cover
            raise AssertionError("gate refusal must not touch the bridge")

        for handler in (serving.handle_revit_decompile,
                        serving.handle_revit_rebuild,
                        serving.handle_revit_idempotence):
            result = _run(handler(
                {"action": "status", "doc_stamp": "docA"}, None, _never_bridge))
            self.assertFalse(result.get("ok", True), msg=result)
            self.assertEqual(result.get("error"), "gate", msg=result)
            self.assertIn("KUKAI_ADMIN_DEVICES", result.get("message_ru", ""),
                          msg=result)

    def test_no_device_literal_survives_in_the_compiler(self) -> None:
        """ХРАПОВИК РАЗВЁРНУТ В СТОРОНУ ДОСТИГНУТОГО: литералов НОЛЬ.

        Прежняя редакция требовала РОВНО ОДИН hex-32 литерал и присутствия
        имени `_MIGRATION_ADMIN_DEVICE` — она сторожила «второго не появилось»,
        пока первый считался неизбежным. 15.08.2026 первый сняли: список
        устройств задаётся только `KUKAI_ADMIN_DEVICES`, фолбэка нет.

        Оставить тест как был значило бы требовать ВОЗВРАТА литерала в файл,
        который публикуется отдельным репозиторием, — то есть охранять
        отменённое состояние. Ноль — это то же правило §18.5 на достигнутой
        отметке: чьё-то устройство в компиляторе не зашито, и обратно оно уже
        не проедет.
        """
        source = Path(serving.__file__).read_text(encoding="utf-8")
        self.assertTrue(source.strip(), "исходник не прочитан — это отказ")
        hits = re.findall(r"[\"'][0-9a-f]{32}[\"']", source)
        self.assertEqual(
            hits, [],
            msg=f"в компилятор вернулся литерал устройства: {hits}")
        # 🔴 ЗАПРЕЩЕНО СВЯЗЫВАНИЕ, А НЕ УПОМИНАНИЕ. Первая редакция этой
        # строки искала само имя и покраснела на КОММЕНТАРИИ, объясняющем,
        # почему фолбэк снят (`serving.py:102`). Запрет упоминания запретил бы
        # документировать собственную историю — а зонд, ловящий ЯРЛЫК вместо
        # ветки, здесь уже покупали не раз. Предмет — присвоение и атрибут
        # модуля; второе проверяется исполнением, а не чтением.
        self.assertIsNone(
            re.search(r"^_MIGRATION_ADMIN_DEVICE\s*=", source, re.M),
            msg="миграционный фолбэк снова ПРИСВАИВАЕТСЯ в компиляторе")
        self.assertFalse(
            hasattr(serving, "_MIGRATION_ADMIN_DEVICE"),
            msg="фолбэк вернулся атрибутом модуля")


class RejectionFeedPath(_EnvGuard):
    _VARS = ("KIR_REJECTIONS_PATH",)

    @staticmethod
    def _one_diagnostic():
        from kukai.ir.diag import Diagnostic
        return Diagnostic(
            code="KIR-G001", message_ru="неизвестный вид", op_index=0,
            field_name="kind", got="ost_nonsense")

    def test_no_env_and_no_local_install_writes_nothing(self) -> None:
        # Замысел прежний: без env и без СВОЕЙ установки фид молчит, а не
        # создаёт чужой каталог. Носитель условия сменился — раньше это был
        # isdir() абсолютного пути в самом модуле, теперь один авторитет
        # install_paths, поэтому «нет своей установки» выражается им.
        os.environ.pop("KIR_REJECTIONS_PATH", None)
        import tempfile
        from kukai.ir import install_paths
        with tempfile.TemporaryDirectory() as bare:
            # каталог без backend/kukai ⇒ install_root() == None
            with mock.patch.object(install_paths, "_INSTALL_ROOT",
                                   Path(bare)):
                self.assertIsNone(coverage_feed._feed_path())
                with mock.patch.object(coverage_feed.os, "makedirs") as makedirs:
                    coverage_feed.record_rejections(
                        [self._one_diagnostic()], [{"op": "create_wall"}])
                makedirs.assert_not_called()

    def test_env_path_is_written(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "kir_rejections.jsonl")
            os.environ["KIR_REJECTIONS_PATH"] = path
            coverage_feed.record_rejections(
                [self._one_diagnostic()], [{"op": "create_wall"}])
            self.assertTrue(os.path.isfile(path))

    def test_module_default_is_not_a_foreign_absolute_path(self) -> None:
        self.assertIsNone(coverage_feed._DEFAULT)


class DecompileOutputRoot(_EnvGuard):
    _VARS = ("KUKAI_DECOMPILE_OUT",)

    def test_env_wins(self) -> None:
        os.environ["KUKAI_DECOMPILE_OUT"] = "/somewhere/else"
        self.assertEqual(
            extract.default_output_root(), Path("/somewhere/else"))

    def test_default_does_not_point_into_a_foreign_installation(self) -> None:
        os.environ.pop("KUKAI_DECOMPILE_OUT", None)
        root = str(extract.default_output_root())
        self.assertFalse(root.startswith("/root"), msg=root)
        self.assertFalse(root.startswith("/opt"), msg=root)
        self.assertEqual(str(extract.DEFAULT_OUTPUT_ROOT), root)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
