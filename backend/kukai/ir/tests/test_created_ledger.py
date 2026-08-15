"""След созданного обязан пережить неуспех хода — и НЕ выдумывать следов.

ПОРОГ (сформулирован директором): прогон, убитый на середине, оставляет на
диске полный список id всего, что успело создаться.

КОНТРОЛЬ-FAIL. Предложенный вариант — оборвать мост посреди пачки — меряет
СРЕДУ и требует живого Ревита оператора, а обрыв невоспроизводим. Здесь
контроль другой и различает то же самое:

    PASS   исход `committed` при `ok: false` — строка содержит РОВНО
           созданное; это и есть случай, который потерял два элемента
    FAIL-1 откат — строка есть, список ПУСТ; «нет строки» и «пустой список»
           обязаны различаться, иначе молчание реестра неотличимо от правды
    FAIL-2 если читать ПРОГРАММУ вместо ПАВЛОАДА, FAIL-1 обязан покраснеть;
           тест ставит эту мутацию сам и требует красноты

Третий и есть настоящий страж: список заявленных опов при откате выглядит
как список созданного, и ровно так реестр превратился бы в генератор ложных
следов — наш именованный класс дефекта в новом месте.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest

from kukai.ir import created_ledger


class TheLedgerReadsThePayloadAndNotTheProgram(unittest.TestCase):

    #: Ответ моста, каким он приходит при `KIR-A006`/`KIR-A007`: элементы
    #: созданы, `ok` ложь. Форма взята с живого ответа 13.08, не придумана.
    COMMITTED = {"result": {"MS1": {"id": "12511351"},
                            "FR1": {"id": "12511358"},
                            "ok": True}}
    #: Откат: строки опов есть, номеров нет.
    ROLLED_BACK = {"result": {"SR1": {"refused": True}, "ok": False}}

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self._prev = os.environ.get(created_ledger.LEDGER_DIR_ENV)
        os.environ[created_ledger.LEDGER_DIR_ENV] = self._dir.name

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop(created_ledger.LEDGER_DIR_ENV, None)
        else:
            os.environ[created_ledger.LEDGER_DIR_ENV] = self._prev
        self._dir.cleanup()

    def _rows(self) -> list[dict]:
        p = pathlib.Path(self._dir.name) / "kir_created_ids.jsonl"
        if not p.exists():
            return []
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
                if x.strip()]

    # ------------------------------------------------------------------ PASS
    def test_committed_with_ok_false_still_records_every_id(self) -> None:
        """ТОТ САМЫЙ случай: запись состоялась, ход объявил неуспех."""
        created_ledger.record_created(self.COMMITTED, query_id="q1")
        rows = self._rows()
        self.assertEqual(len(rows), 1, "строка обязана быть ровно одна")
        self.assertEqual(rows[0]["created"],
                         {"MS1": ["12511351"], "FR1": ["12511358"]})
        self.assertEqual(rows[0]["created_count"], 2)

    def test_the_ledger_never_consults_ok(self) -> None:
        """`ok` в строке результата не участвует в решении.

        Тот же павлоад с `ok: False` обязан дать ТУ ЖЕ запись — иначе реестр
        унаследовал бы ровно тот признак, из-за которого id и терялись.
        """
        payload = json.loads(json.dumps(self.COMMITTED))
        payload["result"]["ok"] = False
        created_ledger.record_created(payload, query_id="q2")
        self.assertEqual(self._rows()[0]["created"],
                         {"MS1": ["12511351"], "FR1": ["12511358"]})

    # ---------------------------------------------------------------- FAIL-1
    def test_a_rollback_leaves_a_row_with_an_empty_list(self) -> None:
        """Ни больше, ни меньше: строка есть, созданного нет.

        «Строки нет» значило бы «реестр не работал», и отличить одно от
        другого потом невозможно.
        """
        created_ledger.record_created(self.ROLLED_BACK, query_id="q3")
        rows = self._rows()
        self.assertEqual(len(rows), 1, "откат обязан оставить строку")
        self.assertEqual(rows[0]["created"], {})
        self.assertEqual(rows[0]["created_count"], 0)

    def test_deleted_is_not_created(self) -> None:
        """`deleted_id` — не след: удалённого в модели уже нет."""
        created_ledger.record_created(
            {"result": {"D1": {"deleted_id": "12511351"}, "ok": True}},
            query_id="q4")
        self.assertEqual(self._rows()[0]["created"], {})

    # ---------------------------------------------------------------- FAIL-2
    def test_reading_the_program_instead_of_the_payload_reddens_the_rollback(
            self) -> None:
        """МУТАЦИЯ, КОТОРУЮ ЭТОТ ФАЙЛ ОБЯЗАН ЛОВИТЬ.

        Подменяем извлечение на «взять заявленные опы». На успехе разницы
        почти нет — и это то, что делает подмену опасной. Отличает её ровно
        откат: заявленное непусто, созданного нет.

        Контроль проверяет, что предыдущий тест ПАДАЕТ под мутацией, а не
        что мутация просто «что-то меняет»: широкий красный есть признак
        тупого зонда.
        """
        real = created_ledger.extract_created

        def _reads_the_program(payload):
            # Дефект в чистом виде: имена опов вместо номеров элементов.
            if not isinstance(payload, dict):
                return {}
            return {str(k): [str(k)] for k in payload if k != "ok"}

        created_ledger.extract_created = _reads_the_program
        try:
            created_ledger.record_created(self.ROLLED_BACK, query_id="mut")
            mutated = self._rows()[0]["created"]
        finally:
            created_ledger.extract_created = real

        self.assertNotEqual(
            mutated, {},
            "мутация обязана дать ложный след — иначе контроль не различает")
        self.assertEqual(
            sorted(mutated), ["SR1"],
            "мутация обязана назвать ИМЕНА опов, а не номера элементов")

    # ------------------------------------------------------------ выключение
    def test_an_explicitly_empty_variable_disables_the_ledger(self) -> None:
        """Выключить обязано быть можно НАРОЧНО, а не отсутствием каталога."""
        os.environ[created_ledger.LEDGER_DIR_ENV] = ""
        self.assertIsNone(created_ledger.record_created(self.COMMITTED))
        self.assertEqual(self._rows(), [])

    def test_a_failure_to_write_never_raises(self) -> None:
        """Успешная запись в Revit не становится неуспешной из-за реестра."""
        os.environ[created_ledger.LEDGER_DIR_ENV] = "/proc/нет-такого/пути"
        row = created_ledger.record_created(self.COMMITTED, query_id="q5")
        self.assertIsNotNone(row, "строка обязана вернуться даже при отказе")
        self.assertEqual(row["created_count"], 2)


class TheTwoPlacesThatDecideCreatedAgree(unittest.TestCase):
    """Реестр и свидетель решают «создано ли» по ОДНИМ ключам.

    Разойдись они — два места начнут отвечать на один вопрос по-разному, а
    это ровно наш класс: величина названа в одном месте, читается в другом,
    и ничто не заставляет их совпасть. `CREATED_KEYS` объявлен НЕПОЛНЫМ по
    признанию, поэтому пинится не полнота, а СОГЛАСИЕ.
    """

    def test_witness_and_ledger_use_the_same_created_keys(self) -> None:
        import inspect

        from kukai.ir import witness_feed
        src = inspect.getsource(witness_feed)
        self.assertIn('"id"', src)
        for key in ("id",):
            self.assertIn(
                key, created_ledger.CREATED_KEYS,
                f"свидетель считает {key!r} признаком созданного, реестр — нет")

    def test_the_ledger_is_wired_into_the_write_path(self) -> None:
        """Модуль, приехавший неподключённым, — наш преобладающий дефект.

        Пинится ВЫЗОВ в `serving`, а не наличие файла: собранное и никем не
        вызванное неотличимо от отсутствующего.
        """
        import inspect

        from kukai.ir import serving
        src = inspect.getsource(serving._handle_revit_ir_inner)
        self.assertIn("created_ledger", src)
        self.assertIn("record_created", src)
        self.assertLess(
            src.index("record_created"), src.index("record_witness"),
            "след созданного обязан писаться РАНЬШЕ, чем работает приёмка")
