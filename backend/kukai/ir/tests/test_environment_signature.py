"""ПОДПИСЬ СРЕДЫ: чем написано — уже подписывалось, НА ЧЁМ посчитано — нет.

ДЫРА, КОТОРУЮ ЭТИ ТЕСТЫ ЗАКРЫВАЮТ. `author_digest` — это sha256 ТЕКСТА скрипта
и больше ничего (`sandbox.execute_author_script`). Ни песочница, ни квитанция,
ни корпус не подписывали ни версию интерпретатора, ни версию ни одной
библиотеки. Следствие ровно одно и оно тяжёлое: обновись shapely или GEOS под
ним между двумя аудитами одного скрипта — ОДИН И ТОТ ЖЕ `author_digest`
удостоверил бы РАЗНЫЕ `program_digest`, и в квитанции не нашлось бы поля, по
которому читатель отличил бы правку скрипта от дрейфа среды. Одно здание, две
подписи — на слое, который до 09.08 не подписывался вовсе.

`replay_check` этого не ловит и не может: он гоняет скрипт ДВАЖДЫ В ОДНОМ
ПРОЦЕССЕ на ОДНОЙ установке и меряет недетерминизм, а не время.

Тесты идут от механизма к квитанции: чистая функция подписи → присутствие блока
в результате настоящего запуска → присутствие в квитанции шлюза → дайджест в
том, что ложится на диск.

    venv/bin/python3.12 -m pytest kukai/ir/tests/test_environment_signature.py -q
"""
from __future__ import annotations

import sys
import types
import unittest

from kukai.ir import sandbox


class TheSignatureNamesTheEnvironment(unittest.TestCase):
    """Чистая функция: что подписывается и чем это получено."""

    def test_interpreter_is_named(self) -> None:
        env = sandbox.environment_signature(("math",))
        self.assertEqual(env["python"],
                         ".".join(str(p) for p in sys.version_info[:3]))
        # Полная строка несёт дату сборки и компилятор: подмена интерпретатора
        # при том же «3.12.13» видна только отсюда.
        self.assertIn(env["python"], env["python_build"])
        self.assertEqual(env["implementation"], sys.implementation.name)
        self.assertEqual(len(env["digest"]), 64)

    def test_every_importable_module_is_named_with_its_version(self) -> None:
        """Подписывается РОВНО белый список — не ручной перечень рядом с ним."""
        env = sandbox.environment_signature(sandbox.ALLOWED_IMPORTS)
        names = [m["name"] for m in env["modules"]]
        self.assertEqual(names, sorted(sandbox.ALLOWED_IMPORTS))
        for row in env["modules"]:
            # stdlib версионируется интерпретатором: своей версии у него нет, и
            # честный ответ — сказать это словом, а не подставить пустую строку.
            self.assertEqual(row["version"], "stdlib")
            self.assertEqual(row["via"], "stdlib")

    def test_a_new_allowed_module_lands_in_the_signature_by_itself(self) -> None:
        """Расширили белый список — подпись выросла БЕЗ правки списка здесь.

        Это и есть требование «поле спроектировано так, что добавленные модули
        попадают в него автоматически»: ручной перечень забыли бы пополнить
        ровно в тот раз, когда это важно.
        """
        probe = types.ModuleType("_kir_env_probe")
        probe.__version__ = "1.0.0"
        sys.modules["_kir_env_probe"] = probe
        try:
            env = sandbox.environment_signature(
                sandbox.ALLOWED_IMPORTS + ("_kir_env_probe",))
            row = next(m for m in env["modules"] if m["name"] == "_kir_env_probe")
            self.assertEqual(row["version"], "1.0.0")
            self.assertEqual(row["via"], "__version__")
            self.assertTrue(row["loaded"])
        finally:
            sys.modules.pop("_kir_env_probe", None)

    def test_the_digest_moves_when_a_library_version_moves(self) -> None:
        """ГЛАВНЫЙ ТЕСТ ФАЙЛА: апгрейд библиотеки СДВИГАЕТ подпись.

        Скрипт не тронут, `author_digest` не тронут — а `env_digest` другой.
        Ровно этого сигнала не было ни в одном поле квитанции.
        """
        probe = types.ModuleType("_kir_env_probe")
        probe.__version__ = "1.0.0"
        sys.modules["_kir_env_probe"] = probe
        try:
            before = sandbox.environment_signature(("_kir_env_probe",))["digest"]
            probe.__version__ = "1.0.1"          # тот же скрипт, новая сборка
            after = sandbox.environment_signature(("_kir_env_probe",))["digest"]
        finally:
            sys.modules.pop("_kir_env_probe", None)
        self.assertNotEqual(before, after)

    def test_the_digest_stands_still_when_nothing_moved(self) -> None:
        """Подпись, которая шевелится сама, ничего не удостоверяет."""
        first = sandbox.environment_signature(sandbox.ALLOWED_IMPORTS)["digest"]
        second = sandbox.environment_signature(sandbox.ALLOWED_IMPORTS)["digest"]
        self.assertEqual(first, second)

    def test_native_versions_are_named_when_the_module_is_loaded(self) -> None:
        """GEOS под shapely — тоже версия, и дрейфует она отдельно от shapely.

        Ищется по ИМЕНИ атрибута, а не по списку библиотек: список знал бы про
        shapely и не знал бы про следующую.
        """
        probe = types.ModuleType("_kir_env_probe")
        probe.__version__ = "1.0.0"
        probe.geos_version = (3, 13, 1)
        probe.geos_version_string = "3.13.1"
        probe._private_version = "не должно попасть"
        sys.modules["_kir_env_probe"] = probe
        try:
            env = sandbox.environment_signature(("_kir_env_probe",))
            row = env["modules"][0]
            self.assertEqual(row["native"],
                             {"geos_version": "3.13.1",
                              "geos_version_string": "3.13.1"})
            before = env["digest"]
            probe.geos_version_string = "3.13.2"   # shapely тот же, GEOS другой
            after = sandbox.environment_signature(("_kir_env_probe",))["digest"]
        finally:
            sys.modules.pop("_kir_env_probe", None)
        self.assertNotEqual(before, after)

    def test_a_module_that_is_not_loaded_says_so(self) -> None:
        """«Нативных фактов нет» и «их не спросили» — разные факты."""
        env = sandbox.environment_signature(("_kir_env_absent",))
        row = env["modules"][0]
        self.assertFalse(row["loaded"])
        self.assertEqual(row["version"], "unknown")
        self.assertNotIn("native", row)


class TheSignatureReachesTheReceipt(unittest.TestCase):
    """Замер, а не намерение: блок доезжает из ребёнка в результат и квитанцию."""

    POLICY = sandbox.SandboxPolicy(replay_check=True)
    SOURCE = ('lvl = create_level(elev_mm=0, name="Этаж 1")\n'
              'create_wall(p0_mm=(0, 0), p1_mm=(5000, 0), level=lvl, '
              'height_mm=3000)\n')

    def test_a_real_run_carries_the_signature(self) -> None:
        result = sandbox.execute_author_script(self.SOURCE, policy=self.POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(len(result.environment["digest"]), 64)
        self.assertEqual(result.env_digest, result.environment["digest"])
        self.assertEqual([m["name"] for m in result.environment["modules"]],
                         sorted(sandbox.ALLOWED_IMPORTS))
        self.assertIn("environment", result.as_dict())
        # Повтор сверяет и среду: обновление ровно между двумя прогонками
        # сделало бы подпись первой прогонки подписью среды, которой уже нет.
        self.assertEqual(result.isolation["environment_replay"], "same")

    def test_a_refused_run_carries_it_too(self) -> None:
        """Подпись среды, в которой скрипт НЕ собрался, — такое же свидетельство."""
        result = sandbox.execute_author_script("1 / 0\n", policy=self.POLICY)
        self.assertFalse(result.ok)
        self.assertEqual(len(result.env_digest), 64)

    def test_the_gateway_receipt_carries_the_whole_block(self) -> None:
        """Аудитор смотрит в квитанцию — значит блок лежит в квитанции.

        Целиком, а не одним дайджестом: дайджест отвечает «поехало ли», блок —
        «что именно», и второй вопрос задаёт тот, у кого первый уже сработал.
        """
        from kukai.ir import serving

        result = sandbox.execute_author_script(self.SOURCE, policy=self.POLICY)
        receipt = serving._authorship_receipt(
            result, source_bytes=len(self.SOURCE.encode("utf-8")))
        self.assertEqual(receipt["environment"], result.environment)
        self.assertEqual(receipt["environment"]["digest"], result.env_digest)

    def test_the_receipt_stays_silent_when_no_child_ran(self) -> None:
        """Отсутствующее остаётся отсутствующим: пустой блок сказал бы
        «среда неизвестна» там, где правда — «скрипт не исполнялся»."""
        from kukai.ir import serving

        result = sandbox.execute_author_script("   \n", policy=self.POLICY)
        self.assertFalse(result.ok)
        self.assertEqual(result.environment, {})
        self.assertNotIn("environment",
                         serving._authorship_receipt(result, source_bytes=4))


class TheSignatureReachesTheDisk(unittest.TestCase):
    """Квитанция живёт один ход; корпус переживает обновления библиотек."""

    def test_the_witness_feed_records_the_env_digest(self) -> None:
        import json
        import os
        import tempfile

        from kukai.ir import witness_feed

        with tempfile.TemporaryDirectory(prefix="kir_env_feed_") as tmp:
            path = os.path.join(tmp, "kir_witness.jsonl")
            previous = os.environ.get("KIR_WITNESS_PATH")
            os.environ["KIR_WITNESS_PATH"] = path
            try:
                witness_feed.record_witness(
                    program={"ops": [{"op": "create_wall", "id": "w1"}]},
                    family="write", revit_version="2026", ok=True,
                    witness=None, duration_ms=1.0,
                    author_digest="a" * 64, env_digest="b" * 64)
            finally:
                if previous is None:
                    os.environ.pop("KIR_WITNESS_PATH", None)
                else:
                    os.environ["KIR_WITNESS_PATH"] = previous
            with open(path, encoding="utf-8") as fh:
                row = json.loads(fh.readlines()[-1])
        self.assertEqual(row["author_digest"], "a" * 64)
        self.assertEqual(row["env_digest"], "b" * 64)

    def test_a_json_program_leaves_no_env_field(self) -> None:
        """Программа, написанную операциями, никакая среда не считала.
        Пустая строка в корпусе читалась бы как «скрипт был и не подписался»."""
        import json
        import os
        import tempfile

        from kukai.ir import witness_feed

        with tempfile.TemporaryDirectory(prefix="kir_env_feed_") as tmp:
            path = os.path.join(tmp, "kir_witness.jsonl")
            previous = os.environ.get("KIR_WITNESS_PATH")
            os.environ["KIR_WITNESS_PATH"] = path
            try:
                witness_feed.record_witness(
                    program={"ops": [{"op": "create_wall", "id": "w1"}]},
                    family="write", revit_version="2026", ok=True,
                    witness=None, duration_ms=1.0)
            finally:
                if previous is None:
                    os.environ.pop("KIR_WITNESS_PATH", None)
                else:
                    os.environ["KIR_WITNESS_PATH"] = previous
            with open(path, encoding="utf-8") as fh:
                row = json.loads(fh.readlines()[-1])
        self.assertNotIn("env_digest", row)
        self.assertNotIn("author_digest", row)


if __name__ == "__main__":
    unittest.main()
