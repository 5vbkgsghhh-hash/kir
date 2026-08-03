"""Читать можно НЕ ТОЛЬКО хозяина: связь — тоже документ.

ЗАМЕР 30.07 на публичной федерации Snowdon Towers. Связанные документы УЖЕ
открыты в сессии (``Application.Documents.Size`` вернул 5), а
``RevitLinkInstance.GetLinkDocument()`` отдаёт готовый ``Document``. То есть
чтобы прочитать связь, открывать не надо НИЧЕГО — достаточно строить
коллекторы против неё.

Открыть связь окном мы всё равно не смогли бы:
``UIApplication.OpenAndActivateDocument`` документирован как «may not be called
from inside an event handler», а наш C# исполняется именно там; живая проба
вернула null, не бросив исключения.

Каждая связь снимается СВОИМ слепком со своим штампом — поэтому ни составных
ключей, ни федеративной переписи, ни правки диалекта не нужно. Тесты ниже
стерегут ровно то, что делает это верным: ВСЕ коллекторы одного тела читают
ОДИН И ТОТ ЖЕ документ, и отсутствие связи — громкий отказ, а не пустое
чтение.
"""
from __future__ import annotations

import re
import unittest

from kukai.ir.decompile.extract import (
    build_category_batch_cs,
    build_category_probe_cs,
    build_metadata_cs,
)
from kukai.security.validation import validate_code_safety

TITLE = "Snowdon Towers Sample Architectural"


def _bodies(link_title):
    return {
        "batch": build_category_batch_cs("OST_Walls", link_title=link_title),
        "probe": build_category_probe_cs("OST_Walls", link_title=link_title),
        "metadata": build_metadata_cs(link_title=link_title),
    }


class SourceBindingTests(unittest.TestCase):

    def test_without_a_link_the_source_is_the_host(self) -> None:
        for name, code in _bodies(None).items():
            with self.subTest(body=name):
                self.assertIn("Document __src = doc;", code)
                # Разрешение связи по имени не эмитируется вовсе.
                self.assertNotIn("__srcLi", code)
                self.assertNotIn("linked document not found", code)

    def test_the_document_identity_follows_the_source(self) -> None:
        """Имя, сведения о проекте и рабочие наборы — ЧИТАЕМОГО документа.

        Иначе слепок связи записал бы в заголовок L0 имя ХОЗЯИНА, и все
        последующие сверки шли бы по чужой identity, не заметив подмены.
        """
        code = build_metadata_cs(link_title=TITLE)
        for expr in ("__src.Title", "__src.ProjectInformation",
                     "__src.IsWorkshared", "FilteredWorksetCollector(__src)"):
            self.assertIn(expr, code)
        for expr in ("doc.Title", "doc.ProjectInformation", "doc.IsWorkshared"):
            self.assertNotIn(expr, code)

    def test_with_a_link_the_source_is_resolved_by_title(self) -> None:
        for name, code in _bodies(TITLE).items():
            with self.subTest(body=name):
                self.assertIn("GetLinkDocument", code)
                self.assertIn(f'"{TITLE}"', code)
                self.assertNotIn("Document __src = doc;", code)

    def test_a_missing_link_is_a_loud_refusal_not_an_empty_read(self) -> None:
        """Пустое чтение выглядело бы как «в связи ничего нет»."""
        code = build_category_batch_cs("OST_Walls", link_title=TITLE)
        self.assertIn("if (__src == null) throw", code)
        self.assertIn("linked document not found or not loaded", code)

    def test_every_collector_in_a_body_reads_the_same_document(self) -> None:
        """Смешать хозяина и связь в одном теле — молча соврать.

        Перепись считала бы хозяина, а элементы приходили бы из связи; закон
        переписи поймал бы расхождение, НЕ НАЗВАВ причины. Поэтому в теле не
        должно остаться ни одного коллектора, построенного против ``doc``.
        """
        for name, code in _bodies(TITLE).items():
            with self.subTest(body=name):
                leaked = re.findall(r"FilteredElementCollector\(doc\)", code)
                # Единственное законное обращение к хозяину — поиск САМОЙ связи.
                allowed = code.count(
                    "foreach (RevitLinkInstance __srcLi in new "
                    "FilteredElementCollector(doc)")
                self.assertEqual(
                    len(leaked), allowed,
                    f"{name}: коллектор читает хозяина вместо связи")

    def test_emitted_bodies_stay_safe_for_both_sources(self) -> None:
        for link_title in (None, TITLE):
            for name, code in _bodies(link_title).items():
                with self.subTest(body=name, link=bool(link_title)):
                    self.assertIsNone(validate_code_safety(code))

    def test_the_title_is_a_c_sharp_literal_not_an_injection(self) -> None:
        """Имя документа приходит извне и обязано ехать литералом."""
        code = build_category_batch_cs(
            "OST_Walls", link_title='Weird" ; DoEvil(); //')
        # Кавычка внутри имени обязана приехать экранированной, а не
        # закрыть литерал и открыть исполняемый хвост.
        self.assertNotIn('"Weird" ;', code)
        self.assertIn('Weird\\"', code)


if __name__ == "__main__":
    unittest.main()
