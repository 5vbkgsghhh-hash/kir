"""An O(n) property-index read inside a comprehension's body makes the work
quadratic.

**FOUND ON A LIVE BUILDING on 2026-08-12, and it could not have been found
offline.** Decompiling the `13A-RD-AR-K2_v33` tower reached the dimensions
stage, handed 13 905 dimensions to the bridge in 207 s — and then hung for 22
minutes at 100% CPU, without writing a single file or a single line to the
manifest. The live process's stack:

    to_dict         dimension_extract.py:216
    dimension_index dimension_extract.py:325
    to_dict         dimension_extract.py:332
    _persist_json   pipeline.py:1185

`DimensionExtraction.dimension_index` is a PROPERTY: every access rebuilds
the whole dictionary from scratch. `to_dict` was reading it INSIDE a
comprehension, once per key — that is, 13 906 full dictionary rebuilds for
13 905 records ≈ 193 million calls to `DimensionRecord.to_dict`. Growth
measurement: n=500 0.21 s, 1000 1.06, 2000 4.62, 4000 21.26 — ×4.6 per
doubling.

**Why no existing test could have seen this: a cost that grows with n is
invisible to any instrument whose n = 3.** The goldens and the contract tests
run 2-5 records, where a square is indistinguishable from a line. This is the
ceiling of offline testing in its pure form — a real building was the only
instrument capable of showing it.

That is why the test here is a COUNTING one, not a timing one: time measures
the machine and gets noisy under load, a call counter measures the algorithm
and answers the same on any hardware. A FAIL control is built in: put the
property read back inside the comprehension, and the first test goes red
with the number n² in the message.
"""

import ast
import pathlib
import unittest

from kir.decompile.dimension_extract import (
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
    """Serialization touches each record EXACTLY ONCE."""

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
        """PASS control: the property IS INDEED O(n) per access.

        Without this, the first test can be green for an uninteresting
        reason — for instance, if someone turns the property into a field.
        Then accesses would stop costing anything, and the test would stop
        measuring what it was written for.
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
    """The shape is closed ACROSS ALL of `kir`, not only at the site where it
    was found.

    The distinction on which the first version of this instrument was lying:
    a property read as the comprehension's SOURCE is computed once and costs
    O(n); read inside the BODY — once per element, and that is O(n²). We
    catch only the latter.
    """

    #: 🔴 THE ROOT IS TAKEN FROM THE PACKAGE'S LOCATION (28.08.2026). This
    #: used to say `parents[3] / "ir"`: before the split the package was
    #: called `ir` and lived inside `kukai/`. After the `kukai/ir` -> `kir`
    #: rename, the same count points to `/opt/kir/ir`, which does not exist,
    #: and the walk was finding ZERO modules. This test's own control
    #: ("0 not greater than 100 — the root is broken, not the code") fired
    #: correctly and named the cause itself.
    #: We count from `kir.__file__`, not by steps upward — by the
    #: `install_paths` rule.
    ROOT = pathlib.Path(__import__("kir").__file__).resolve().parent

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
        """Control on both ends on one sample.

        Inside the body — it finds it; as the source — it is silent. Exactly
        this difference distinguishes a square from a line, and exactly on
        it the first version of the instrument was lying, reporting a false
        site in `sketch_extract`.
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
