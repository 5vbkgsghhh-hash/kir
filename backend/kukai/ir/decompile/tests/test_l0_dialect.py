"""Диалект L0 обязан иметь имя, а старые слепки — обязаны читаться.

ЧТО СЛОМАЛОСЬ И ПОЧЕМУ ЭТО НЕ РЕГРЕСС ОДНОЙ ВОЛНЫ. 29.07 таблица чтения
выросла 54 -> 73 (ee32fb82), и все прежние слепки перестали открываться через
``L0JSONLReader``: «footer precedes one or more fixed categories». Разбор
показал, что виновата не эта волна. ``L0_SCHEMA_VERSION`` не менялся НИ РАЗУ,
а таблица росла ШЕСТЬ раз (22 -> 47 -> 48 -> 51 -> 54 -> 73), то есть каждый
прошлый рост так же обесценивал накопленное, просто никто не пробовал открыть
старый слепок новым кодом.

ТРИ НЕЗАВИСИМЫХ ИСТОЧНИКА СОШЛИСЬ (замер 29.07):

* история git по ``extract.py`` — шесть различных таблиц, каждая следующая
  начинается ровно с предыдущей;
* байты на диске — 55 слепков в ``backend/data/decompile``: 22 шт. по 22
  категории, 9 по 47, 12 по 48, 1 по 51, 10 по 54, плюс один прерванный на 7
  без футера; последовательность ``category_status`` КАЖДОГО из них —
  точный префикс сегодняшней таблицы из 73 строк;
* отпечатки: sha256 по историческим кортежам из git совпали с отпечатками по
  байтам с диска для всех шести поколений, расхождений ноль.

Отсюда закон, который этот файл и охраняет: **таблица растёт ТОЛЬКО дописью в
хвост**. Он и раньше был записан словами в комментарии ``extract.py`` («порядок
этого кортежа — часть замороженного формата возобновления»), но не был ни
проверяем, ни назван версией. Пока он держится, поколение однозначно задаётся
ОДНИМ числом — длиной таблицы; как только его нарушат, ``verify_dialect_ladder``
обязан закричать, а не переосмыслить старые байты молча.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from kukai.ir.decompile.extract import (
    EXTRACT_CATEGORIES,
    ExtractionProtocolError,
    L0JSONLReader,
    _load_checkpoint,
)
from kukai.ir.decompile.census import (
    UnscannedReason,
    reconcile_census,
)
from kukai.ir.decompile.schema import (
    SUPPORTED_L0_DIALECTS,
    SUPPORTED_L0_DIALECT_VERSIONS,
    L0_DIALECT_VERSION,
    L0_SCHEMA_VERSION,
    CensusEntry,
    L0Dialect,
    L0Document,
    L0SchemaError,
    ProjectInfo,
    categories_outside_dialect,
    dialect_by_version,
    dialect_fingerprint,
    resolve_dialect,
    verify_dialect_ladder,
)
from kukai.ir.decompile.tests.fixtures_decompile import make_element


def _snapshot_root() -> Path:
    """Каталог настоящих слепков — тот же, что читает serving.py."""
    configured = os.environ.get("KUKAI_DECOMPILE_DATA")
    if configured:
        return Path(configured)
    # kukai/ir/decompile/tests -> .../backend, затем backend/data/decompile.
    return Path(__file__).resolve().parents[4] / "backend" / "data" / "decompile"


def _write_stream(
    path: Path,
    *,
    categories,
    elements_per_category: int = 0,
    footer_category_count: int | None = None,
    dialect: str | None = None,
) -> None:
    """Записать поток L0 ровно так, как его пишет extract (сжатый JSON)."""

    def dump(row) -> bytes:
        return json.dumps(row, ensure_ascii=False, separators=(",", ":"),
                          sort_keys=True).encode("utf-8") + b"\n"

    document = L0Document(
        doc_name="dialect-fixture",
        revit_version="2026",
        units="mm",
        change_stamp=path.parent.name,
        levels=(),
        grids=(),
        rooms=(),
        project_info=ProjectInfo(),
    )
    total = 0
    with path.open("wb") as handle:
        header = {"record": "header", "schema_version": L0_SCHEMA_VERSION,
                  "document": document.metadata_dict()}
        if dialect is not None:
            header["dialect"] = dialect
        handle.write(dump(header))
        for ordinal, category in enumerate(categories):
            for index in range(elements_per_category):
                row = make_element(category, 900_000 + total, ordinal=index)
                handle.write(dump({
                    "record": "element", "collector": category,
                    "element": row}))
                total += 1
            handle.write(dump({"record": "category_status", "status": {
                "category": category, "state": "complete",
                "extracted_count": elements_per_category,
                "expected_count": elements_per_category,
                "error": None, "section_receipts": None}}))
        footer = {"record": "footer", "stream_complete": True,
                  "element_count": total, "link_count": 0,
                  "category_count": (len(list(categories))
                                     if footer_category_count is None
                                     else footer_category_count)}
        handle.write(dump(footer))


class DialectLadderTests(unittest.TestCase):
    """Лестница поколений — данные, и они обязаны сходиться с таблицей."""

    def test_current_table_is_the_newest_generation(self) -> None:
        """Свежая таблица обязана БЫТЬ последней ступенью лестницы.

        Иначе следующая волна вырастит таблицу, забудет ступень — и свежий
        слепок откажется читаться СВОИМ ЖЕ читателем. Пусть падает здесь.
        """
        newest = SUPPORTED_L0_DIALECTS[-1]
        self.assertEqual(newest.category_count, len(EXTRACT_CATEGORIES),
                         "таблица выросла, а ступень диалекта не заведена")
        self.assertEqual(newest.version, L0_DIALECT_VERSION)
        self.assertEqual(
            newest.fingerprint, dialect_fingerprint(EXTRACT_CATEGORIES))

    def test_every_generation_is_a_prefix_of_todays_table(self) -> None:
        """Отпечаток ступени = отпечаток префикса сегодняшней таблицы.

        Отпечатки взяты из ИСТОРИИ (git + байты на диске), а не посчитаны от
        сегодняшней таблицы, поэтому сравнение не круговое: оно и есть
        доказательство, что за шесть ростов ни одна строка не вставлена в
        середину и не переименована.
        """
        verify_dialect_ladder(EXTRACT_CATEGORIES)
        for dialect in SUPPORTED_L0_DIALECTS:
            prefix = EXTRACT_CATEGORIES[:dialect.category_count]
            self.assertEqual(len(prefix), dialect.category_count)
            self.assertEqual(dialect_fingerprint(prefix), dialect.fingerprint,
                             f"{dialect.version} больше не префикс таблицы")

    def test_versions_and_counts_are_strictly_increasing(self) -> None:
        counts = [d.category_count for d in SUPPORTED_L0_DIALECTS]
        self.assertEqual(counts, sorted(set(counts)),
                         "ступени обязаны идти строго по возрастанию")
        self.assertEqual(len(set(SUPPORTED_L0_DIALECT_VERSIONS)),
                         len(SUPPORTED_L0_DIALECT_VERSIONS))
        for version in SUPPORTED_L0_DIALECT_VERSIONS:
            self.assertIs(dialect_by_version(version).version.__class__, str)

    def test_mid_table_insertion_is_refused_loudly(self) -> None:
        """ОПРОВЕРГАЮЩИЙ: вставка в середину обязана кричать.

        Ровно этот случай — единственный, при котором «поколение = длина»
        перестаёт работать и старые байты можно молча переосмыслить: строка
        N в потоке означала бы одну категорию, а в таблице — другую.
        """
        table = list(EXTRACT_CATEGORIES)
        table.insert(10, "OST_Massing")
        with self.assertRaises(L0SchemaError) as caught:
            verify_dialect_ladder(table)
        self.assertIn("kir-decompile-l0-dialect/", str(caught.exception))

    def test_renaming_a_frozen_row_is_refused(self) -> None:
        """ОПРОВЕРГАЮЩИЙ: переименование строки — та же подмена смысла."""
        table = list(EXTRACT_CATEGORIES)
        table[0] = "OST_WallsRenamed"
        with self.assertRaises(L0SchemaError):
            verify_dialect_ladder(table)

    def test_truncating_the_table_is_refused(self) -> None:
        """ОПРОВЕРГАЮЩИЙ: усечение таблицы — потеря уже названного поколения."""
        with self.assertRaises(L0SchemaError):
            verify_dialect_ladder(EXTRACT_CATEGORIES[:-1])

    def test_resolve_names_the_generation_by_count(self) -> None:
        for dialect in SUPPORTED_L0_DIALECTS:
            resolved = resolve_dialect(dialect.category_count,
                                       EXTRACT_CATEGORIES)
            self.assertEqual(resolved.version, dialect.version)

    def test_resolve_refuses_a_count_that_is_no_generation(self) -> None:
        """Число категорий, которого не было НИ В ОДНОЙ сборке, — не поколение.

        Догадка «наверное, это префикс» здесь запрещена: мы не знаем, что
        такая сборка считала полнотой, а значит не вправе называть её поток
        полным.
        """
        with self.assertRaises(L0SchemaError) as caught:
            resolve_dialect(30, EXTRACT_CATEGORIES)
        message = str(caught.exception)
        self.assertIn("30", message)
        self.assertIn(SUPPORTED_L0_DIALECTS[-1].version, message)

    def test_absent_categories_are_named_not_zero(self) -> None:
        """Неполнота обязана быть ПОИМЁННОЙ, а не молчаливым нулём."""
        oldest = SUPPORTED_L0_DIALECTS[0]
        absent = categories_outside_dialect(oldest, EXTRACT_CATEGORIES)
        self.assertEqual(len(absent),
                         len(EXTRACT_CATEGORIES) - oldest.category_count)
        self.assertIn("OST_TelephoneDevices", absent)
        self.assertNotIn("OST_Walls", absent)
        newest = SUPPORTED_L0_DIALECTS[-1]
        self.assertEqual(
            categories_outside_dialect(newest, EXTRACT_CATEGORIES), ())


class ReaderReadsEveryGenerationTests(unittest.TestCase):
    """Читатель обязан открывать КАЖДОЕ названное поколение."""

    def test_every_generation_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for dialect in SUPPORTED_L0_DIALECTS:
                with self.subTest(dialect=dialect.version):
                    path = Path(tmp) / f"L0_{dialect.category_count}.jsonl"
                    _write_stream(
                        path,
                        categories=EXTRACT_CATEGORIES[:dialect.category_count],
                        elements_per_category=1)
                    reader = L0JSONLReader(path)
                    elements = list(reader.iter_elements())
                    self.assertEqual(len(elements), dialect.category_count)
                    self.assertEqual(reader.dialect().version, dialect.version)

    def test_unknown_generation_is_refused_and_named(self) -> None:
        """ОПРОВЕРГАЮЩИЙ: поток на 30 категорий отвергается, и громко."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            _write_stream(path, categories=EXTRACT_CATEGORIES[:30])
            with self.assertRaises(ExtractionProtocolError) as caught:
                L0JSONLReader(path).validate()
            self.assertIn("30", str(caught.exception))

    def test_reader_still_refuses_a_reordered_stream(self) -> None:
        """Защита от перестановки НЕ ослабла: порядок по-прежнему закон."""
        swapped = list(EXTRACT_CATEGORIES[:22])
        swapped[0], swapped[1] = swapped[1], swapped[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            _write_stream(path, categories=swapped, elements_per_category=1)
            with self.assertRaises(ExtractionProtocolError):
                L0JSONLReader(path).validate()

    def test_reader_still_refuses_a_lying_footer(self) -> None:
        """Футер, называющий чужое число категорий, по-прежнему отвергается."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            _write_stream(path, categories=EXTRACT_CATEGORIES[:22],
                          footer_category_count=73)
            with self.assertRaises(ExtractionProtocolError) as caught:
                L0JSONLReader(path).validate()
            self.assertIn("footer category count", str(caught.exception))


class RealSnapshotCorpusTests(unittest.TestCase):
    """Доказательство на НАСТОЯЩИХ байтах, а не на фикстуре.

    Фикстура доказывает, что код согласован сам с собой. Накопленный корпус
    (55 слепков шести поколений, 1.8 ГБ) доказывает, что он согласован с тем,
    что действительно снято с живых моделей за одиннадцать дней. Именно эта
    проверка 29.07 подтвердила бамп индекса витражей, и здесь она обязана
    быть такой же.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _snapshot_root()
        if not cls.root.is_dir():
            raise unittest.SkipTest(f"нет корпуса слепков: {cls.root}")
        cls.by_generation: dict[int, list[Path]] = {}
        for directory in sorted(cls.root.iterdir()):
            stream = directory / "L0.jsonl"
            if not stream.is_file():
                continue
            count = 0
            with stream.open("rb") as handle:
                for line in handle:
                    if b'"record":"category_status"' in line:
                        count += 1
            cls.by_generation.setdefault(count, []).append(stream)
        if not cls.by_generation:
            raise unittest.SkipTest("корпус пуст")

    def test_corpus_covers_several_generations(self) -> None:
        known = {d.category_count for d in SUPPORTED_L0_DIALECTS}
        covered = sorted(set(self.by_generation) & known)
        self.assertGreaterEqual(
            len(covered), 3,
            f"нужно хотя бы три РАЗНЫХ поколения, есть {covered}")

    def test_one_snapshot_of_every_generation_reads_end_to_end(self) -> None:
        """Каждое поколение из корпуса читается ЦЕЛИКОМ, до футера."""
        known = {d.category_count: d for d in SUPPORTED_L0_DIALECTS}
        checked = 0
        for count, streams in sorted(self.by_generation.items()):
            if count not in known:
                continue
            stream = min(streams, key=lambda path: path.stat().st_size)
            with self.subTest(generation=count, snapshot=stream.parent.name):
                reader = L0JSONLReader(stream)
                elements = sum(1 for _ in reader.iter_elements())
                statuses = list(reader.iter_category_status())
                self.assertEqual(len(statuses), count)
                self.assertEqual(reader.dialect().version,
                                 known[count].version)
                self.assertEqual(
                    [status.category for status in statuses],
                    list(EXTRACT_CATEGORIES[:count]))
                self.assertGreater(elements, 0)
                checked += 1
        self.assertGreaterEqual(checked, 3)

    def test_interrupted_snapshots_still_refuse(self) -> None:
        """Прерванный слепок (без футера) обязан отказывать — он и НЕ полон.

        Версионирование лечит «старый, но целый», а не «оборванный». Смешать
        эти два случая означало бы выдать недоизвлечённую модель за снятую.
        """
        refused = 0
        for streams in self.by_generation.values():
            for stream in streams:
                with stream.open("rb") as handle:
                    handle.seek(max(0, stream.stat().st_size - 4096))
                    tail = handle.read()
                if b'"record":"footer"' in tail:
                    continue
                with self.assertRaises(ExtractionProtocolError):
                    L0JSONLReader(stream).validate()
                refused += 1
        if not refused:
            self.skipTest("в корпусе нет оборванных слепков")


class CensusReadsTheSnapshotsOwnTableTests(unittest.TestCase):
    """Перепись обязана мерить слепок ЕГО таблицей, а не сегодняшней."""

    def _document(self, categories, census_counts):
        from kukai.ir.decompile.schema import CategoryState, CategoryStatus
        elements = []
        for category in categories:
            count = census_counts.get(category, 0)
            for index in range(count):
                from kukai.ir.decompile.schema import L0Element
                row = make_element(category, 700_000 + len(elements),
                                   ordinal=index)
                elements.append(L0Element.from_dict(row))
        return L0Document(
            doc_name="census-fixture", revit_version="2026", units="mm",
            change_stamp="census", levels=(), grids=(), rooms=(),
            project_info=ProjectInfo(),
            elements=tuple(elements),
            category_status=tuple(
                CategoryStatus(category=category,
                               state=CategoryState.COMPLETE,
                               extracted_count=census_counts.get(category, 0),
                               expected_count=census_counts.get(category, 0))
                for category in categories),
            census=tuple(
                CensusEntry(key=key, name=key, count=count)
                for key, count in census_counts.items()),
        )

    def test_category_added_after_the_snapshot_is_outside_its_table(self) -> None:
        """ОПРОВЕРГАЮЩИЙ: категория, которой в таблице ТОГДА не было.

        До версионирования такая строка получала ``category_short_read`` —
        «извлечение читало и недочитало», — то есть слепку приписывался
        отказ, которого он не совершал. Правильная причина ровно одна:
        категории не было в таблице того поколения.
        """
        oldest = SUPPORTED_L0_DIALECTS[0]
        visited = EXTRACT_CATEGORIES[:oldest.category_count]
        newcomer = EXTRACT_CATEGORIES[-1]
        counts = {visited[0]: 3, newcomer: 5}
        document = self._document(visited, counts)
        balance = reconcile_census(document)
        rows = {row.category: row for row in balance.rows}
        self.assertIn(newcomer, rows)
        self.assertEqual(rows[newcomer].reason,
                         UnscannedReason.CATEGORY_OUTSIDE_TABLE)
        self.assertEqual(rows[newcomer].unscanned, 5)
        self.assertFalse(balance.errors)

    def test_explicit_table_still_wins(self) -> None:
        """Явно переданная таблица по-прежнему главнее вывода из потока."""
        oldest = SUPPORTED_L0_DIALECTS[0]
        visited = EXTRACT_CATEGORIES[:oldest.category_count]
        newcomer = EXTRACT_CATEGORIES[-1]
        document = self._document(visited, {visited[0]: 1, newcomer: 2})
        balance = reconcile_census(
            document, table=frozenset(EXTRACT_CATEGORIES))
        rows = {row.category: row for row in balance.rows}
        self.assertEqual(rows[newcomer].reason,
                         UnscannedReason.CATEGORY_SHORT_READ)


class ResumeAcrossDialectsTests(unittest.TestCase):
    """Что делать с ВОЗОБНОВЛЕНИЕМ слепка, снятого старой таблицей.

    Решение и его цена — в докстринге ``_load_checkpoint``. Здесь оно
    закреплено обоими исходами: оборванный продолжаем, законченный — нет.
    """

    def _checkpoint(self, tmp: Path, *, processed, footer_written,
                    dialect=None):
        output = tmp / "L0.jsonl"
        output.write_bytes(b"")
        row = {
            "schema_version": L0_SCHEMA_VERSION,
            "change_stamp": "stamp",
            "output_path": str(output.resolve()),
            "committed_offset": 1,
            "header_written": True,
            "footer_written": footer_written,
            "processed_categories": list(processed),
            "category_states": {c: "complete" for c in processed},
            "element_count": 0,
            "link_count": 0,
        }
        if dialect is not None:
            row["dialect"] = dialect
        path = tmp / "L0.jsonl.checkpoint.json"
        path.write_text(json.dumps(row), encoding="utf-8")
        return path, output

    def test_interrupted_old_generation_resumes(self) -> None:
        """Оборванный прогон старой таблицы ПРОДОЛЖАЕТСЯ.

        Дописка в хвост доказана: уже обработанные категории — те же строки
        с теми же индексами, доизвлекать можно без сдвига.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, output = self._checkpoint(
                tmp, processed=EXTRACT_CATEGORIES[:22], footer_written=False,
                dialect=SUPPORTED_L0_DIALECTS[0].version)
            row = _load_checkpoint(path, change_stamp="stamp",
                                   output_path=output)
            self.assertEqual(len(row["processed_categories"]), 22)

    def test_interrupted_checkpoint_without_a_dialect_resumes(self) -> None:
        """Чекпойнт ДО версионирования тоже продолжается — но неназванно.

        Таких на диске 55 из 55: отказать им значило бы выбросить всю
        накопленную незаконченную работу ради поля, которого тогда не
        существовало.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, output = self._checkpoint(
                tmp, processed=EXTRACT_CATEGORIES[:7], footer_written=False)
            row = _load_checkpoint(path, change_stamp="stamp",
                                   output_path=output)
            self.assertEqual(len(row["processed_categories"]), 7)

    def test_finished_old_generation_refuses_to_be_extended(self) -> None:
        """ОПРОВЕРГАЮЩИЙ: законченный слепок НЕ дописывается.

        ``stream_complete`` — единственный закон этого контейнера. Поток,
        однажды сказавший «полон», не вправе потом сказать «не полон»: это
        не доизвлечение, а ретроактивная правка опубликованного факта.
        Читать такой слепок можно (и он читается — см. корпусные тесты),
        дописывать — нет.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, output = self._checkpoint(
                tmp, processed=EXTRACT_CATEGORIES[:54], footer_written=True,
                dialect="kir-decompile-l0-dialect/5")
            with self.assertRaises(ExtractionProtocolError) as caught:
                _load_checkpoint(path, change_stamp="stamp",
                                 output_path=output)
            message = str(caught.exception)
            self.assertIn("kir-decompile-l0-dialect/5", message)
            self.assertIn(L0_DIALECT_VERSION, message)

    def test_finished_current_generation_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, output = self._checkpoint(
                tmp, processed=EXTRACT_CATEGORIES, footer_written=True,
                dialect=L0_DIALECT_VERSION)
            row = _load_checkpoint(path, change_stamp="stamp",
                                   output_path=output)
            self.assertTrue(row["footer_written"])

    def test_checkpoint_dialect_must_be_a_known_generation(self) -> None:
        """ОПРОВЕРГАЮЩИЙ: чужая версия диалекта — отказ, а не догадка."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, output = self._checkpoint(
                tmp, processed=EXTRACT_CATEGORIES[:22], footer_written=False,
                dialect="kir-decompile-l0-dialect/99")
            with self.assertRaises(ExtractionProtocolError):
                _load_checkpoint(path, change_stamp="stamp",
                                 output_path=output)


if __name__ == "__main__":
    unittest.main()
