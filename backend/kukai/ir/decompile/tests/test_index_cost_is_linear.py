"""Свойство-индекс O(n), прочитанное в теле включения, делает работу квадратичной.

**Найдено НА ЖИВОМ ЗДАНИИ 2026-08-12, и офлайн найти это было нельзя.** Разбор
башни `13A-RD-AR-K2_v33` дошёл до стадии размеров, отдал мостом 13 905 размеров
за 207 с — и встал на 22 минуты со 100% CPU, не написав ни файла, ни строки в
манифест. Стек живого процесса:

    to_dict         dimension_extract.py:216
    dimension_index dimension_extract.py:325
    to_dict         dimension_extract.py:332
    _persist_json   pipeline.py:1185

`DimensionExtraction.dimension_index` — СВОЙСТВО: каждое обращение строит весь
словарь заново. `to_dict` читал его ВНУТРИ включения, на каждый ключ, то есть
13 906 полных пересборок словаря на 13 905 записей ≈ 193 млн вызовов
`DimensionRecord.to_dict`. Замер роста: n=500 0.21 с, 1000 1.06, 2000 4.62,
4000 21.26 — ×4.6 на удвоение.

**Почему этого не мог увидеть ни один существующий тест: стоимость, растущая с
n, невидима любому прибору, у которого n = 3.** Голдены и контрактные тесты
гоняют 2–5 записей, где квадрат неотличим от линии. Это потолок офлайна в
чистом виде — настоящее здание было единственным прибором, способным показать.

Поэтому тест здесь СЧЁТНЫЙ, а не временной: время меряет машину и шумит под
нагрузкой, счётчик вызовов меряет алгоритм и отвечает одинаково на любом
железе. Контроль-FAIL встроен: верните чтение свойства внутрь включения, и
первый тест покраснеет с числом n² в сообщении.
"""

import ast
import pathlib
import unittest

from kukai.ir.decompile.dimension_extract import (
    DimensionExtraction,
    DimensionRecord,
)


def _extraction(count: int) -> DimensionExtraction:
    return DimensionExtraction(dimensions=tuple(
        DimensionRecord(
            element_id=str(1_000_000 + index),
            owner_view_id="1",
            owner_view_name="вид",
            line_at_view_mm=(1.0, 2.0),
            ref_element_ids=("a", "b"),
            segment_count=1,
            dimension_shape="Linear",
        )
        for index in range(count)
    ))


class IndexIsBuiltOnce(unittest.TestCase):
    """Сериализация трогает каждую запись РОВНО ОДИН раз."""

    def test_to_dict_calls_each_record_exactly_once(self):
        count = 40
        extraction = _extraction(count)
        calls = []
        original = DimensionRecord.to_dict

        def counting(record):
            calls.append(record.element_id)
            return original(record)

        DimensionRecord.to_dict = counting
        try:
            payload = extraction.to_dict()
        finally:
            DimensionRecord.to_dict = original

        self.assertEqual(len(payload["dimension_index"]), count)
        self.assertEqual(
            len(calls), count,
            f"сериализация вызвала to_dict {len(calls)} раз на {count} записей "
            f"(квадрат дал бы {count * (count + 1)}) — свойство-индекс "
            f"строится заново внутри включения")

    def test_the_property_itself_is_the_expensive_one(self):
        """Контроль-PASS: свойство ДЕЙСТВИТЕЛЬНО O(n) на каждое обращение.

        Без этого первый тест зелен и по неинтересной причине — например, если
        кто-то превратит свойство в поле. Тогда обращения перестанут стоить, и
        тест перестанет мерить то, ради чего написан.
        """
        count = 12
        extraction = _extraction(count)
        calls = []
        original = DimensionRecord.to_dict

        def counting(record):
            calls.append(record.element_id)
            return original(record)

        DimensionRecord.to_dict = counting
        try:
            extraction.dimension_index
            extraction.dimension_index
        finally:
            DimensionRecord.to_dict = original

        self.assertEqual(
            len(calls), count * 2,
            "два обращения к свойству должны стоить 2n — если это уже поле, "
            "первый тест больше ничего не охраняет и его надо переписать")


class NoPropertyIsReadInsideAComprehension(unittest.TestCase):
    """Форма закрыта ПО ВСЕМУ `kukai/ir`, а не только на найденной площадке.

    Различие, на котором врал первый вариант этого прибора: свойство,
    прочитанное как ИСТОЧНИК включения, вычисляется один раз и стоит O(n);
    прочитанное в ТЕЛЕ — на каждый элемент, и это O(n²). Ловим только второе.
    """

    ROOT = pathlib.Path(__file__).resolve().parents[3] / "ir"

    @staticmethod
    def _linear_properties(tree: ast.Module) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for member in node.body:
                if not isinstance(member, ast.FunctionDef):
                    continue
                if not any(isinstance(decorator, ast.Name)
                           and decorator.id == "property"
                           for decorator in member.decorator_list):
                    continue
                if any(isinstance(inner,
                                  (ast.DictComp, ast.ListComp, ast.SetComp))
                       for inner in ast.walk(member)):
                    names.add(member.name)
        return names

    @classmethod
    def _findings(cls, path: pathlib.Path) -> list[tuple[int, str]]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        properties = cls._linear_properties(tree)
        if not properties:
            return []
        found: list[tuple[int, str]] = []
        for comp in ast.walk(tree):
            if not isinstance(comp, (ast.DictComp, ast.ListComp, ast.SetComp)):
                continue
            sources = {id(node)
                       for generator in comp.generators
                       for node in ast.walk(generator.iter)}
            body = ([comp.key, comp.value]
                    if isinstance(comp, ast.DictComp) else [comp.elt])
            body += [test
                     for generator in comp.generators
                     for test in generator.ifs]
            for part in body:
                for node in ast.walk(part):
                    if not isinstance(node, ast.Attribute):
                        continue
                    if id(node) in sources:
                        continue
                    if (node.attr in properties
                            and isinstance(node.value, ast.Name)
                            and node.value.id == "self"):
                        found.append((node.lineno, node.attr))
        return found

    def test_no_module_reads_a_linear_property_per_element(self):
        offenders = []
        scanned = 0
        for path in sorted(self.ROOT.rglob("*.py")):
            if "/tests/" in path.as_posix():
                continue
            scanned += 1
            for line, name in self._findings(path):
                offenders.append(
                    f"{path.relative_to(self.ROOT)}:{line} self.{name}")
        self.assertGreater(scanned, 100,
                           "развёртка не нашла модулей — сломан корень, "
                           "а не код")
        self.assertEqual(
            offenders, [],
            "свойство O(n) читается в теле включения — на каждый элемент; "
            "прочитайте его ОДИН раз в локальную переменную:\n  "
            + "\n  ".join(offenders))

    def test_the_scan_can_tell_the_body_from_the_source(self):
        """Контроль по обоим концам на одном образце.

        В теле — находит; как источник — молчит. Ровно эта разница отличает
        квадрат от линии, и ровно на ней врал первый вариант прибора,
        выдававший ложную площадку в `sketch_extract`.
        """
        module = ast.parse(
            "class C:\n"
            "    @property\n"
            "    def idx(self):\n"
            "        return {r.k: r for r in self.rows}\n"
            "    def in_body(self):\n"
            "        return {k: self.idx[k] for k in self.keys}\n"
            "    def as_source(self):\n"
            "        return {k: 1 for k in sorted(self.idx)}\n")
        properties = self._linear_properties(module)
        self.assertEqual(properties, {"idx"})

        lines = []
        for comp in ast.walk(module):
            if not isinstance(comp, ast.DictComp):
                continue
            sources = {id(node)
                       for generator in comp.generators
                       for node in ast.walk(generator.iter)}
            for node in ast.walk(comp.value):
                if (isinstance(node, ast.Attribute) and node.attr == "idx"
                        and id(node) not in sources):
                    lines.append(node.lineno)
        self.assertEqual(
            lines, [6],
            "прибор обязан найти чтение в ТЕЛЕ (строка 6) и не считать "
            "находкой чтение в ИСТОЧНИКЕ (строка 8)")


if __name__ == "__main__":
    unittest.main()
