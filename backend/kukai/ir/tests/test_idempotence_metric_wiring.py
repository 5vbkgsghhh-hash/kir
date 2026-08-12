"""АКСЕССОР МЕТРИКИ: РАБОТАЕТ МЕХАНИЗМ, НЕ РАБОТАЕТ ОБЕЩАНИЕ ДОКСТРИНГА.

ЗАМЕР 11.08.2026 — три факта, и каждый отменяет часть подозрения:

  1. МЕХАНИЗМ ЖИВ. `idempotence.json` лежит рядом с восемью разборами,
     свежайший `sob62_fas_r23_v18` от 29.07.2026: 44 ключа настоящих данных,
     `raw_exact_pct` 85.808, `multiset_match` False. Прогоны БЫЛИ.
     (Архивная записка `docs/archive/NOTES_A5.md` говорит «живой прогон НЕ
     запускался» — она СТАРШЕ прогонов, ровно как корпус был старше волны
     `host_source`.)
  2. ПАМЯТНЫЙ СЛОВАРЬ НЕСЁТ СВОЙСТВО КОРРЕКТНОСТИ, а не просто значение:
     `test_serving_idempotence.test_cleanup_failure_is_top_level_failure_and_
     not_dashboard_success` требует, чтобы `_last_idempotence` ОСТАЛСЯ ПУСТ,
     когда уборка провалилась. Прогон с несостоявшейся уборкой не смеет
     попасть в панель успехом. Удалить словарь — снять это требование.
  3. НЕ ВЫЗЫВАЕТСЯ РОВНО ОДНА ВЕЩЬ — двухстрочный аксессор
     `last_idempotence_metric()`. Стоит он ноль (копия словаря по запросу),
     поэтому довод «дороже вычисления нуля» к нему не применим.

ЧТО ЖЕ ТОГДА СЛОМАНО. Докстринг: «Dashboard hook: the last A5 run's exact% and
date (or None)» описывает ЖИВУЮ ПРОВОДКУ, которой нет, — и это соседняя семья
нашего класса: инструмент, в работоспособность которого легко поверить,
потому что имя и докстринг описывают несуществующее.

И ВТОРОЕ, ХУЖЕ ПЕРВОГО, И ЭТО УЖЕ НАШ КЛАСС. Словарь живёт В ПАМЯТИ ПРОЦЕССА,
а артефакт — на диске. После перезапуска аксессор вернёт `None` при восьми
состоявшихся прогонах. То есть `None` означает СРАЗУ ДВА разных факта:
«в этом процессе прогонов не было» и «прогонов не было никогда». Ровно та
неразличимость, которую весь марафон разводили: молчание прибора против
чистого результата.

ПОЭТОМУ НИ ПОДКЛЮЧИТЬ, НИ УДАЛИТЬ ЗДЕСЬ НЕЛЬЗЯ МОЛЧА. Удалить — снять
единственный НАЗВАННЫЙ путь чтения (потребитель полез бы в приватный словарь).
Подключить по-настоящему — значит решить, читает ли аксессор диск, а для этого
нужен `doc_stamp`: разборов восемь, а аргументов у него нет. Это подпись под
несуществующего потребителя, то есть догадка.

Здесь поэтому запирается РОВНО ТО, ЧТО ИЗМЕРЕНО: пока вызывающих нет,
докстринг обязан это говорить; появится вызывающий — тест заставит переписать
докстринг, а не оставить в нём вчерашнее обещание.
"""
from __future__ import annotations

import inspect
import pathlib
import re
import unittest

from kukai.ir import serving as S


_ROOT = pathlib.Path(S.__file__).resolve().parents[2]
#: Файлы, где упоминание имени НЕ является вызовом: определение и этот тест.
_NOT_A_CALLER = {"serving.py", "test_idempotence_metric_wiring.py"}
#: Маркер, которым докстринг признаёт отсутствие потребителя.
_DISCLAIMER = "ПОТРЕБИТЕЛЯ НЕТ"


def _callers() -> list[str]:
    """Файлы дерева, которые ЗОВУТ аксессор (а не просто называют его)."""
    hits: list[str] = []
    for path in _ROOT.rglob("*.py"):
        if path.name in _NOT_A_CALLER or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if re.search(r"last_idempotence_metric\s*\(", text):
            hits.append(str(path.relative_to(_ROOT)))
    return sorted(hits)


class TheDocstringMatchesTheWiring(unittest.TestCase):
    """ЗАМОК СКЛАДА: обещание в докстринге обязано совпадать с проводкой."""

    def test_the_docstring_admits_it_has_no_consumer(self):
        doc = inspect.getdoc(S.last_idempotence_metric) or ""
        if _callers():
            self.assertNotIn(
                _DISCLAIMER, doc,
                f"потребитель появился ({_callers()}), а докстринг всё ещё "
                f"говорит, что его нет")
        else:
            self.assertIn(
                _DISCLAIMER, doc,
                "вызывающих нет, а докстринг обещает живую проводку")

    def test_the_summary_line_no_longer_claims_a_hook(self):
        """Проверяется ПЕРВАЯ СТРОКА, а не весь текст: докстринг обязан иметь
        право процитировать снятое обещание, объясняя, что именно снято.
        Утверждает же за функцию именно сводная строка."""
        doc = inspect.getdoc(S.last_idempotence_metric) or ""
        summary = doc.splitlines()[0] if doc else ""
        self.assertNotIn("hook", summary.lower())
        self.assertNotIn("Dashboard", summary)

    def test_the_restart_hole_is_named(self):
        """`None` после перезапуска и `None` при отсутствии прогонов — разные
        факты, и пока они неразличимы, это обязано быть НАПИСАНО."""
        doc = inspect.getdoc(S.last_idempotence_metric) or ""
        self.assertIn("idempotence.json", doc)
        self.assertIn("перезапуск", doc.lower())


class TheMechanismItselfStaysAlive(unittest.TestCase):
    """Удалять было НЕЧЕГО: и словарь, и персист несут работу."""

    def test_the_in_memory_summary_still_exists(self):
        self.assertIsInstance(S._last_idempotence, dict)

    def test_an_empty_metric_is_none_not_an_empty_dict(self):
        """`None` и `{}` — разные ответы; пустой словарь читался бы как
        «прогон был и оказался пуст»."""
        saved = dict(S._last_idempotence)
        S._last_idempotence.clear()
        try:
            self.assertIsNone(S.last_idempotence_metric())
        finally:
            S._last_idempotence.update(saved)

    def test_the_accessor_hands_out_a_copy_not_the_dict(self):
        """Отдать сам словарь значит дать читателю править метрику."""
        saved = dict(S._last_idempotence)
        S._last_idempotence.clear()
        S._last_idempotence.update({"doc_stamp": "d", "raw_exact_pct": 1.0})
        try:
            out = S.last_idempotence_metric()
            out["doc_stamp"] = "подменено"
            self.assertEqual(S._last_idempotence["doc_stamp"], "d")
        finally:
            S._last_idempotence.clear()
            S._last_idempotence.update(saved)


if __name__ == "__main__":
    unittest.main()
