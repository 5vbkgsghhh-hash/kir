"""Боковая стадия читает ТОТ ЖЕ документ, что и основное извлечение.

ЗАМЕР 30.07, слепок ``backend/data/decompile/snowdon_elec_v1`` — связанная
электрика, снятая из окна сантехники. Основное извлечение уже умело читать
связь, а боковые стадии — нет: их коллекторы искали запрошенные id в ХОЗЯИНЕ.

    стадия                      квитанций   из них element_unresolved
    family_placement                 1837                       1770
    annotation                         89                         87
    curve / sketch / curtain      1 / 1 / 1                        3

И это была ЛУЧШАЯ половина беды. Хуже вторая: у 20 id хозяин ВЕРНУЛ элемент с
тем же числовым id, и стадия записала его как строку связи. Элемент связи
``1442277`` — ``OST_ElectricalEquipment``, а в индексе размещения у него
семейство ``Tee - Generic`` (тройник сантехники ХОЗЯИНА); ``1442799`` —
``OST_ConduitFitting``, в индексе ``Elbow - Generic``. Пустая квитанция громко
говорит «не прочитал»; такая строка молча врёт, и опровергнуть её нечем —
у документов РАЗНЫЕ пространства идентификаторов, а числа в них совпадают.

Отсюда закон, который стерегут тесты ниже: ВСЕ обращения к документу внутри
ОДНОГО эмитированного тела идут к ОДНОМУ документу (``__src``), и
единственное законное обращение к хозяину — поиск САМОЙ связи.
"""
from __future__ import annotations

import asyncio
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kukai.ir.decompile import pipeline as pipe
from kukai.ir.decompile.annotation_extract import build_annotation_extract_cs
from kukai.ir.decompile.curtain_extract import build_curtain_extract_cs
from kukai.ir.decompile.curve_extract import build_curve_extract_cs
from kukai.ir.decompile.extract import _source_binding_cs
from kukai.ir.decompile.family_placement_extract import (
    build_family_placement_extract_cs,
)
from kukai.ir.decompile.geom_extract import (
    GEOMETRY_EXTRACT_SCHEMA_VERSION,
    build_geometry_extract_cs,
)
from kukai.ir.decompile.group_extract import build_group_extract_cs
from kukai.ir.decompile.mep_system_extract import build_mep_system_extract_cs
from kukai.ir.decompile.side_contract import source_binding_cs
from kukai.ir.decompile.sketch_extract import build_sketch_extract_cs
from kukai.ir.decompile.tag_extract import build_tag_extract_cs
from kukai.ir.decompile.tests.test_pipeline import FakePipelineBridge
from kukai.security.validation import validate_code_safety

TITLE = "Snowdon Towers Sample Electrical"

#: Каждая боковая стадия — по одному телу на источник. Список полный
#: НАМЕРЕННО: стадия, забытая здесь, — это ровно тот случай, который дал 1837
#: квитанций, и единственная защита от него — перечисление всех съёмщиков.
STAGES = {
    "annotation": lambda title: build_annotation_extract_cs(
        ["1442277"], link_title=title),
    "tag": lambda title: build_tag_extract_cs(
        ["1442277"], revit_version=2024, link_title=title),
    "mep_system": lambda title: build_mep_system_extract_cs(
        ["1442277"], link_title=title),
    "family_placement": lambda title: build_family_placement_extract_cs(
        ["1442277"], link_title=title),
    "curve": lambda title: build_curve_extract_cs(
        ["1442277"], link_title=title),
    "sketch": lambda title: build_sketch_extract_cs(
        ["1442277"], link_title=title),
    "curtain": lambda title: build_curtain_extract_cs(
        ["1442277"], link_title=title),
    "group": lambda title: build_group_extract_cs(link_title=title),
    "geometry": lambda title: build_geometry_extract_cs(
        ["1442277"], link_title=title),
}


def _strip_comments(code: str) -> str:
    """Убрать комментарии C#, НЕ трогая строковые литералы.

    Нужно ровно затем, чтобы упоминание ``doc`` в пояснении (в
    ``sketch_extract`` процитирована сигнатура ``Railing.Create(doc, ...)``)
    не считалось чтением документа, а настоящее чтение внутри литерала не
    пряталось за случайными ``//``.
    """
    out: list[str] = []
    i = 0
    n = len(code)
    while i < n:
        ch = code[i]
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                if code[i] == "\\" and i + 1 < n:
                    out.append(code[i])
                    out.append(code[i + 1])
                    i += 2
                    continue
                out.append(code[i])
                closing = code[i] == '"'
                i += 1
                if closing:
                    break
            continue
        if ch == "/" and i + 1 < n and code[i + 1] == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and code[i + 1] == "*":
            i += 2
            while i + 1 < n and not (code[i] == "*" and code[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class SideStageSourceBindingTests(unittest.TestCase):

    def test_without_a_link_the_source_is_the_host(self) -> None:
        for stage, build in STAGES.items():
            with self.subTest(stage=stage):
                code = build(None)
                self.assertIn("Document __src = doc;", code)
                self.assertNotIn("__srcLi", code)
                self.assertNotIn("linked document not found", code)

    def test_with_a_link_the_source_is_resolved_by_title(self) -> None:
        for stage, build in STAGES.items():
            with self.subTest(stage=stage):
                code = build(TITLE)
                self.assertIn("GetLinkDocument", code)
                self.assertIn(f'"{TITLE}"', code)
                self.assertNotIn("Document __src = doc;", code)

    def test_a_missing_link_is_a_loud_refusal_not_an_empty_read(self) -> None:
        """«В связи ничего нет» неотличимо от успеха — значит запрещено."""
        for stage, build in STAGES.items():
            with self.subTest(stage=stage):
                code = build(TITLE)
                self.assertIn("if (__src == null) throw", code)
                self.assertIn("linked document not found or not loaded", code)

    def test_every_read_in_a_body_goes_to_the_same_document(self) -> None:
        """Единственное законное обращение к хозяину — поиск САМОЙ связи.

        Проверяется не «нет коллектора по ``doc``», а более сильное: после
        вычитания преамбулы связи слово ``doc`` в теле не встречается ВООБЩЕ.
        Именно ``doc.GetElement`` (а не коллектор) увёл 1770 id стадии
        размещения в квитанции и подсунул 20 чужих строк.
        """
        for stage, build in STAGES.items():
            for link_title in (None, TITLE):
                with self.subTest(stage=stage, link=bool(link_title)):
                    code = build(link_title)
                    binding = source_binding_cs(link_title)
                    self.assertIn(binding, code)
                    rest = _strip_comments(code.replace(binding, "", 1))
                    leaked = sorted({
                        match.group(0)
                        for match in re.finditer(r"\bdoc\b[^\s]{0,14}", rest)})
                    self.assertEqual(
                        [], leaked,
                        f"{stage}: тело читает хозяина вместо источника")

    def test_the_binding_is_emitted_before_the_first_read(self) -> None:
        """Локальная переменная C# не видна выше своего объявления.

        Стадия, где привязка приехала ПОСЛЕ хелперов, не собралась бы у
        Roslyn, а не «прочитала бы не то» — но узнать об этом можно было бы
        только живьём, из окна, которое сейчас занято разбором.
        """
        for stage, build in STAGES.items():
            for link_title in (None, TITLE):
                with self.subTest(stage=stage, link=bool(link_title)):
                    code = build(link_title)
                    self.assertTrue(
                        code.startswith(source_binding_cs(link_title)),
                        f"{stage}: привязка источника не первая в теле")

    def test_emitted_bodies_stay_safe_for_both_sources(self) -> None:
        for stage, build in STAGES.items():
            for link_title in (None, TITLE):
                with self.subTest(stage=stage, link=bool(link_title)):
                    self.assertIsNone(validate_code_safety(build(link_title)))

    def test_the_title_is_a_c_sharp_literal_not_an_injection(self) -> None:
        """Имя документа приходит извне и обязано ехать литералом."""
        for stage, build in STAGES.items():
            with self.subTest(stage=stage):
                code = build('Weird" ; DoEvil(); //')
                self.assertNotIn('"Weird" ;', code)
                self.assertIn('Weird\\"', code)

    def test_the_side_binding_is_the_same_text_as_the_main_one(self) -> None:
        """Две привязки — две правды о том, что читается; поэтому одна.

        ``extract._source_binding_cs`` и ``side_contract.source_binding_cs``
        обязаны давать БАЙТ В БАЙТ один C#: закон «одно тело — один документ»
        проверяется по тексту, и разошедшиеся тексты сделали бы проверку
        зелёной при разном поведении.
        """
        for link_title in (None, TITLE, 'Weird" ; DoEvil(); //'):
            with self.subTest(link=link_title):
                self.assertEqual(
                    _source_binding_cs(link_title),
                    source_binding_cs(link_title))


class SideStageSourceWiringTests(unittest.TestCase):
    """ПРОВОДКА, а не только эмиссия.

    Волна оформления 30.07 прошла все свои тридцать тестов и умерла на стыке:
    дефект был не в стадии и не в её C#, а в том, чего тесты стадии не
    касались. Источник — ровно такой же стык: правильный ``build_*_cs`` не
    значит ничего, пока конвейер не передал ему ``link_title``.
    """

    #: Полный набор зарегистрированных боковых стадий. Список ЗАКРЫТ
    #: намеренно: новая стадия, забывшая источник, обязана уронить этот тест,
    #: а не тихо унести ещё полторы тысячи id в квитанции.
    REGISTERED = {
        "curve", "curtain", "sketch", "family_placement", "group",
        "annotation", "dimension", "tag", "mep_system", "geometry",
    }

    def test_the_factory_hands_the_source_to_every_registered_stage(self):
        builders = pipe._default_cs_builders(
            revit_version=2024, link_title=TITLE)
        self.assertEqual(self.REGISTERED, set(builders))
        binding = source_binding_cs(TITLE)
        for stage, build in builders.items():
            with self.subTest(stage=stage):
                code = build(["1442277"])
                self.assertTrue(
                    code.startswith(binding),
                    f"{stage}: конвейер собрал тело без источника")
                rest = _strip_comments(code.replace(binding, "", 1))
                self.assertEqual(
                    [], sorted({m.group(0) for m in re.finditer(
                        r"\bdoc\b[^\s]{0,14}", rest)}),
                    f"{stage}: тело конвейера читает хозяина")

    def test_the_host_is_the_source_when_no_link_is_asked_for(self):
        for stage, build in pipe._default_cs_builders(
                revit_version=2024).items():
            with self.subTest(stage=stage):
                self.assertIn("Document __src = doc;", build(["1442277"]))

    def test_a_whole_run_asks_the_link_in_every_call_it_makes(self):
        """Через ВЕСЬ конвейер: боковые стадии и проба Д2 вокруг них.

        Проба здесь не украшение: сторож, считающий ХОЗЯИНА вокруг стадии,
        читающей связь, согласится сам с собой при любой правке внутри связи
        — то есть перестанет быть сторожем, оставшись зелёным.
        """
        bodies: list[str] = []

        class Recording(FakePipelineBridge):
            async def __call__(self, code: str, *, timeout_ms: int):
                bodies.append(code)
                return await super().__call__(code, timeout_ms=timeout_ms)

        with TemporaryDirectory() as tmp:
            bridge = Recording(link_title=TITLE)
            result = asyncio.run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="link-wiring-v1",
                link_title=TITLE))
        self.assertTrue(result.ok, msg=result.to_dict())
        # Стадии, которые эта модель действительно кормит id-ами.
        self.assertEqual(
            ["curve", "sketch", "curtain", "family_placement", "group",
             "geometry"],
            [call for call in bridge.side_calls
             if call != "open_model_profile"])

        binding = source_binding_cs(TITLE)
        # Ревизионный страж — ЕДИНСТВЕННОЕ законное чтение хозяина сверх
        # поиска связи: он отпечатывает документ ХОЗЯИНА и на связи
        # concurrent-правку не ловит (оговорка ``_source_binding_cs``).
        guard = pipe._REVISION_FINGERPRINT_CS
        side = [
            code for code in bodies
            if any(marker in code for marker in (
                "kir-decompile-curve-extract", "kir-decompile-sketch-extract",
                "kir-decompile-curtain-extract",
                "kir-decompile-family-placement-extract",
                "kir-decompile-group-extract",
                GEOMETRY_EXTRACT_SCHEMA_VERSION))
        ]
        self.assertGreaterEqual(len(side), 6)
        for code in side:
            self.assertIn(binding, code)
            rest = _strip_comments(
                code.replace(guard, "", 1).replace(binding, "", 1))
            self.assertEqual(
                [], sorted({m.group(0) for m in re.finditer(
                    r"\bdoc\b[^\s]{0,14}", rest)}))

        probes = [code for code in bodies
                  if '{"count", __total}, {"levels", __scopes}' in code]
        self.assertTrue(probes, "проба Д2 не эмитировалась вовсе")
        for code in probes:
            self.assertIn(binding, code)

    def test_an_index_from_another_document_is_not_reused(self) -> None:
        """Счётчик строк не отличает хозяина от связи — а источник обязан.

        Каталог ``snowdon_elec_v1`` — живой пример: его боковые индексы сняты
        по заказу от связи, а прочитаны у хозяина. Схема правильная, строк
        столько же, счётчик безупречен. Переиспользовать такой индекс на
        прогоне связи значит унаследовать чужой документ через диск — уже
        после того, как эмиссия починена.
        """
        with TemporaryDirectory() as tmp:
            host = FakePipelineBridge()
            first = asyncio.run(pipe.run_decompile(
                host, out_dir=tmp, change_stamp="link-reuse-v1"))
            self.assertTrue(first.ok, msg=first.to_dict())
            manifest = json.loads(
                (Path(tmp) / pipe._SIDE_MANIFEST_NAME).read_text("utf-8"))
            self.assertEqual(
                {None},
                {row["source"] for row in manifest["stages"].values()})

            # Тот же каталог, но теперь спрашивают СВЯЗЬ: ни одна стадия не
            # имеет права приехать с диска.
            linked = FakePipelineBridge(link_title=TITLE)
            second = asyncio.run(pipe.run_decompile(
                linked, out_dir=tmp, change_stamp="link-reuse-v1",
                link_title=TITLE))
            self.assertTrue(second.ok, msg=second.to_dict())
            for stage in ("curve", "sketch", "curtain", "family_placement",
                          "group", "geometry"):
                self.assertIn(stage, linked.side_calls)
            manifest = json.loads(
                (Path(tmp) / pipe._SIDE_MANIFEST_NAME).read_text("utf-8"))
            self.assertEqual(
                {TITLE},
                {row["source"] for row in manifest["stages"].values()})

            # А тот же источник во второй раз — переиспользуется, как и был.
            again = FakePipelineBridge(link_title=TITLE)
            third = asyncio.run(pipe.run_decompile(
                again, out_dir=tmp, change_stamp="link-reuse-v1",
                link_title=TITLE))
            self.assertTrue(third.ok, msg=third.to_dict())
            self.assertEqual([], [
                call for call in again.side_calls
                if call != "open_model_profile"])


if __name__ == "__main__":
    unittest.main()
