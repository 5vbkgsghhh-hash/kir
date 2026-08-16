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

from kukai.ir import created_ledger, witness_feed


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
    и ничто не заставляет их совпасть. Оба места теперь спрашивают ОДИН
    авторитет — реестр опов, — поэтому пинится и полнота, и согласие.
    """

    def test_witness_and_ledger_use_the_same_created_keys(self) -> None:
        """Оба места решают «создано ли» ОДНИМ авторитетом — реестром.

        🔴 ПРЕЖНЯЯ РЕДАКЦИЯ ЭТОГО ТЕСТА НЕ УМЕЛА ПОКРАСНЕТЬ (снято 15.08.2026).
        Она проверяла `'"id"' in inspect.getsource(witness_feed)` — строка
        `"id"` встречается в семисотстрочном модуле заведомо — и затем
        перебирала кортеж из ОДНОГО элемента, проверяя `"id" in CREATED_KEYS`,
        то есть константу. Тест стоял зелёным ровно тогда, когда два места
        разошлись на `segment_ids`: четыре созидающих опа реестр терял, а
        свидетель метил `other`. Сторож, который не умеет сказать «нет», хуже
        отсутствующего: он создаёт уверенность и не даёт защиты.

        Здесь сверяется ПОВЕДЕНИЕ на строке результата, а не наличие подстроки
        в исходнике.

        🔴 И ВТОРАЯ РЕДАКЦИЯ ТОЖЕ БЫЛА ВАКУУМНОЙ — поймано мутацией, а не
        рассуждением. Она перебирала `created_identity_fields()`, то есть
        СПРАШИВАЛА ТУ САМУЮ ВЕЛИЧИНУ, КОТОРУЮ ПРОВЕРЯЕТ: подмени эту функцию
        старым рукописным кортежем — и тест зелен, потому что честно сверяет
        подменённое с подменённым. Авторитет теста обязан быть НЕЗАВИСИМ от
        предмета, поэтому ожидание берётся у `spec.OPS` напрямую.
        """

        from kukai.ir.registry_base import EffectKind
        from kukai.ir import spec

        expected = {op.result.identity_field for op in spec.OPS.values()
                    if op.effect is EffectKind.CREATE and op.result.identity_field}
        self.assertTrue(expected, "реестр не дал ни одного созидающего поля")
        self.assertEqual(
            set(created_ledger.created_keys()), expected,
            "ключи реестра следов разошлись с реестром ОПЕРАЦИЙ")

        for field in sorted(expected):
            value = 4242 if field == "id" else [4242]
            self.assertTrue(
                created_ledger.extract_created({"o1": {field: value}}),
                f"реестр следов не считает {field!r} созданным, а реестр опов — да")
            self.assertEqual(
                witness_feed.outcome_label({field: value}), "created",
                f"свидетель не считает {field!r} созданным, а реестр опов — да")

    def test_the_agreement_check_can_actually_fail(self) -> None:
        """КОНТРОЛЬ-FAIL сверки, и он проверен МУТАЦИЕЙ, а не надеждой.

        Поле, которого реестр не знает, не «создано» — раз. И два: вернув
        рукописный кортёж, каким он был до 15.08, сверка обязана ПОКРАСНЕТЬ.
        Без второй половины первая доказывает только, что мусор не проходит.
        """

        self.assertFalse(created_ledger.extract_created({"o1": {"нет_такого": 7}}))
        self.assertEqual(witness_feed.outcome_label({"нет_такого": 7}), "other")

        from kukai.ir import address
        real = address.created_identity_fields
        address.created_identity_fields = lambda: ("id", "ids", "created_ids")
        try:
            with self.assertRaises(AssertionError):
                self.test_witness_and_ledger_use_the_same_created_keys()
        finally:
            address.created_identity_fields = real

    def test_moved_is_not_created_and_that_is_a_decision(self) -> None:
        """`moved_ids` исключён НАЗВАННО, а не молча выпал из кортежа."""

        self.assertIn("moved_ids", created_ledger.not_created_keys())
        self.assertNotIn("moved_ids", created_ledger.created_keys())
        self.assertFalse(created_ledger.extract_created({"m1": {"moved_ids": [1]}}))
        self.assertEqual(witness_feed.outcome_label({"moved_ids": [1]}), "other")

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
