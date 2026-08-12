"""ХРАПОВИК СПИСКОВ-ЗАПИСЕЙ: ни одной записи без даты, ни одной без срока.

ЗАЧЕМ ЭТОТ НАБОР СУЩЕСТВУЕТ. За 09.08.2026 в шести независимых работах
барьером оказался не код, а честно заведённая ЗАПИСЬ о коде, пережившая свой
факт: имя в списке долгов читается потребителем как ЗАМЕР, и никто не приходит
перемерить. Полная постановка и три проверенных примера — в шапке
``kukai/ir/record_ratchet.py``.

ЭТО НЕ ВТОРОЙ ХРАПОВИК. Механизм один и живёт в ``record_ratchet``; журнал
тёмных МОДУЛЕЙ (``tests/test_capability_reachability.py``, часть третья) берёт
оттуда ту же строку, тот же порог и те же проверки формы. Здесь — сторож над
журналами ЗАПИСЕЙ компилятора.

ГРАНИЦА НАБОРА, НАЗВАННАЯ СРАЗУ, А НЕ В ОГОВОРКЕ. Он проверяет ФОРМУ и СРОК.
Он НЕ проверяет, что причина всё ещё правда: это умеет только прибор своей
предметной области, и у половины журналов этот прибор ВНЕ дерева (корпус живых
свидетелей — машинно-локальный, в ``.gitignore``). Поэтому срок здесь не
украшение, а единственное, что заставляет человека сходить к прибору. Набор,
который делал бы вид, что проверяет правдивость, был бы ровно тем «прибором на
часть диапазона», против которого всё это написано.
"""
from __future__ import annotations

import importlib
import pathlib
import re
import unittest

from kukai.ir import record_ratchet as rr
from kukai.ir.record_ratchet import CLOSE_BY, STANDS, Entry, Ledger

_IR_DIR = pathlib.Path(__file__).resolve().parents[1]
_BACKEND = _IR_DIR.parents[1]

#: Объявление журнала в исходнике: ``ИМЯ = Ledger(`` на верхнем уровне.
_LEDGER_DECL = re.compile(r"^\s*(\w+)\s*=\s*Ledger\(", re.M)


def _modules_declaring_a_ledger() -> dict[str, str]:
    """``модуль -> исходник`` по всем файлам пакета, включая тестовые.

    Сканируется ИСХОДНИК, а не память процесса. Журнал, объявленный в модуле,
    который этот набор не импортирует, иначе просто не попал бы в
    ``ALL_LEDGERS`` — и новый список-запись завёлся бы мимо храповика, ровно
    тем способом, которым заводились все прежние.
    """
    found: dict[str, str] = {}
    for path in sorted(_IR_DIR.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        if not _LEDGER_DECL.search(src):
            continue
        rel = path.relative_to(_BACKEND).with_suffix("")
        found[".".join(rel.parts)] = src
    return found


def _all_ledgers() -> dict[str, Ledger]:
    for module in _modules_declaring_a_ledger():
        importlib.import_module(module)
    return dict(rr.ALL_LEDGERS)


class EveryRecordListIsDatedAndExpires(unittest.TestCase):

    def test_every_ledger_entry_carries_a_decision_and_a_date(self):
        """Форма проверяется, а не подразумевается.

        Запись без вердикта или без разбираемой даты — это снова «оставим как
        есть», только длиннее. Форма ловится уже при ИМПОРТЕ (``Ledger``
        роняет модуль), и этот тест — второй рубеж: он же печатает всё разом,
        когда журналов станет много.
        """
        for name, ledger in sorted(_all_ledgers().items()):
            with self.subTest(ledger=name):
                bad = rr.check_form(ledger.entries, verdicts=ledger.verdicts,
                                    standing=ledger.standing,
                                    min_reason=ledger.min_reason)
                self.assertEqual(bad, [], "\n".join([""] + bad))

    def test_a_record_decision_expires_and_demands_a_new_one(self):
        """ТО, РАДИ ЧЕГО ВСЁ ЭТО ЗАВЕДЕНО.

        Тест НАМЕРЕННО зависит от календаря и покраснеет на строках, которых
        к их дню не тронут. Правильная реакция — перемерить ПРИБОРОМ журнала
        (он назван в самом журнале) и закрыть, удалить либо написать решение
        заново с новой датой. Неправильная — подвинуть дату, не приняв
        решения: это видно в ``git log -p`` одной строкой диффа, и именно так
        учёт превращается в кладбище.
        """
        for name, ledger in sorted(_all_ledgers().items()):
            with self.subTest(ledger=name):
                overdue, stale = rr.check_expiry(ledger.entries)
                self.assertEqual(
                    [n for n, _ in overdue], [],
                    f"СРОК ВЫШЕЛ. Перемерить: {ledger.instrument}")
                self.assertEqual(
                    [n for n, _ in stale], [],
                    f"решение старше {rr.REVIEW_DAYS} дней — подтвердить или "
                    f"пересмотреть. Перемерить: {ledger.instrument}")

    def test_a_new_entry_cannot_be_declared_without_a_date(self):
        """ОПРОВЕРГАЮЩИЙ ТЕСТ ПОД ГЛАВНЫЙ РИСК: через неделю всё вернётся.

        Дисциплина, которая держится на памяти, не держится. Здесь она
        держится конструкцией: строка без даты, без срока или с вердиктом не
        из словаря делает НЕИМПОРТИРУЕМЫМ модуль, который её объявил, — та же
        форма, что у ``WitnessCheck``, который нельзя построить без вердикта.
        """
        good = Entry(CLOSE_BY, "2026-08-09", "2026-09-08", "причина " * 8)
        for broken, why in (
            (Entry(CLOSE_BY, "", "2026-09-08", "причина " * 8),
             "без даты решения"),
            (Entry(CLOSE_BY, "2026-08-09", "", "причина " * 8),
             "без срока при закрываемом пробеле"),
            (Entry("как-нибудь", "2026-08-09", "2026-09-08", "причина " * 8),
             "с вердиктом не из словаря"),
            (Entry(CLOSE_BY, "2026-08-09", "2026-08-01", "причина " * 8),
             "со сроком раньше самого решения"),
            (Entry(CLOSE_BY, "2026-08-09", "2026-09-08", "коротко"),
             "с причиной-заглушкой"),
            (Entry(CLOSE_BY, "2999-01-01", "2999-02-01", "причина " * 8),
             "с решением из будущего"),
        ):
            with self.subTest(case=why):
                with self.assertRaises(rr.RecordFormError,
                                       msg=f"запись {why} построилась"):
                    Ledger("проба", {"x": broken},
                           instrument="проба прибора для опровергающего теста")
        # Обратная сторона: исправная запись обязана строиться, иначе тест
        # выше проходил бы вакуумно.
        Ledger("проба-исправная", {"x": good},
               instrument="проба прибора для опровергающего теста")
        # И журнал без названного прибора тоже невозможен: просроченную
        # строку иначе будут «проверять» её же комментарием.
        with self.assertRaises(rr.RecordFormError):
            Ledger("проба-без-прибора", {"x": good}, instrument="—")

    def test_every_ledger_in_the_sources_reaches_this_ratchet(self):
        """Сторож над самим храповиком.

        Журнал, объявленный в модуле, который этот набор не импортирует, не
        попадёт в ``ALL_LEDGERS`` и будет стареть молча — то есть новый
        список-запись завёлся бы ровно тем способом, которым заводились все
        прежние. Поэтому список журналов не пишется здесь наизусть, а
        снимается с ИСХОДНИКОВ.
        """
        declared = _modules_declaring_a_ledger()
        self.assertTrue(declared, "в пакете не нашлось ни одного журнала — "
                                  "либо сканер сломан, либо храповик снят")
        registered = _all_ledgers()
        self.assertTrue(registered)
        # Каждое объявление в исходнике обязано дать зарегистрированный
        # журнал: имя журнала — первый аргумент `Ledger(...)`, и оно же ключ.
        for module, src in sorted(declared.items()):
            names = re.findall(r"Ledger\(\s*\n?\s*\"([^\"]+)\"", src)
            for name in names:
                with self.subTest(module=module, ledger=name):
                    self.assertIn(
                        name, registered,
                        f"{module} объявляет журнал {name!r}, но он не дошёл "
                        f"до ALL_LEDGERS — храповик его не увидит")

    def test_the_shared_mechanism_is_the_one_the_dark_ledger_uses(self):
        """ВТОРОГО ХРАПОВИКА НЕТ, И ЭТО ПРОВЕРЯЕТСЯ, А НЕ ОБЕЩАЕТСЯ.

        Журнал тёмных модулей и журналы записей обязаны иметь ОДНУ форму
        строки и ОДИН порог протухания. Разойдясь, они сделали бы слово
        «просрочено» разным в двух местах одного дерева — а это ровно тот
        класс дефекта (две записи об одном факте), из-за которого всё
        затевалось.
        """
        from tests import test_capability_reachability as dark
        self.assertIs(dark.REVIEW_DAYS, rr.REVIEW_DAYS)
        self.assertEqual(dark.Dark._fields, Entry._fields)
        self.assertTrue(issubclass(dark.Dark, Entry))


class TheCaptureGapsAreDatedToo(unittest.TestCase):
    """Пробелы захвата — журнал по существу, но живут в дataclass'е контракта,
    а не в отдельной таблице: у обратного хода одна строка на оп, и заводить
    рядом вторую значило бы завести два места правды об одном опе."""

    def test_every_capture_gap_carries_a_decision_and_a_deadline(self):
        from kukai.ir.reverse_contract import REVERSE_CONTRACTS, ReverseMode
        gaps = {c.op_name: Entry(CLOSE_BY, c.decided_on, c.due, c.reason)
                for c in REVERSE_CONTRACTS.values()
                if c.mode is ReverseMode.CAPTURE_GAP}
        self.assertTrue(gaps)
        self.assertEqual(
            rr.check_form(gaps, verdicts=(CLOSE_BY,), standing=STANDS), [])
        overdue, stale = rr.check_expiry(gaps)
        self.assertEqual(
            [n for n, _ in overdue], [],
            "срок пробела захвата вышел. Перемерить: категория в "
            "extract.EXTRACT_CATEGORIES и названное поле в extract.py — "
            "если захват уже читает их, строка неверна и обязана уехать в "
            "direct, а не ждать")
        self.assertEqual([n for n, _ in stale], [])

    def test_a_capture_gap_without_a_date_is_unconstructible(self):
        """Опровергающий тест: форма ловится при построении контракта."""
        from kukai.ir.reverse_contract import (
            ReverseContract, ReverseGuarantee, ReverseMode)
        with self.assertRaises(ValueError):
            ReverseContract("create_topography", ReverseMode.CAPTURE_GAP,
                            ReverseGuarantee.NONE, "причина есть, даты нет")
        with self.assertRaises(ValueError):
            ReverseContract("create_topography", ReverseMode.CAPTURE_GAP,
                            ReverseGuarantee.NONE, "срок раньше решения",
                            decided_on="2026-08-09", due="2026-08-01")
        # А неsapture_gap-контракт не имеет права нести дату: даты — про то,
        # чего обратный ход ПОКА не умеет, а не про то, чем он является.
        with self.assertRaises(ValueError):
            ReverseContract("create_wall", ReverseMode.DIRECT,
                            ReverseGuarantee.FORM_EXACT, "лишняя дата",
                            entrypoints=("_lift_wall",),
                            decided_on="2026-08-09", due="2026-09-08")


if __name__ == "__main__":
    unittest.main()
