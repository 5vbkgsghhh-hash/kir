"""A census of the unconnected: counts THE SAME THING it displays, and
distinguishes a design from a debt.

🔴 WHY THIS GUARD EXISTS — THE DEFECT WAS IN THE REPORT, NOT THE SCANNER.

On 2026-08-27 the breakdown by module was counted over ALL 273 lines, but
printed right under the "called by nobody: 179" block. Two people in a row
attributed it to that line, in one evening, both careful.

The cost: `checker/fixtures/builders.py 16` read as "sixteen fixtures
called by nobody," whereas in "nobody" their count is EXACTLY ZERO — all
sixteen are called by the owner's own tests, and the scanner KNEW this.

**The instrument was right, the report was not.** Form 24: the unit of
MEASUREMENT and the unit of the REPORT are different things, and the
second breaks independently of the first; a control on the instrument does
not catch this, because the instrument is correct. And form 23: a
statement has not only text but a PLACE, and the place is part of the
statement.

The guard's second subject is the `by_construction` kind. "Not called" is
a DEBT; "CANNOT be called by name" is a DESIGN. Conflating them means
recording a port's protocol as debt — precisely the thing for which the
package is separated from the host.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import textwrap
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# 🔴 THE INSTRUMENT MOVED INTO THE PACKAGE ON 2026-08-28: `tools/` is not
# part of the installable package, and importing by the short name was
# CROSSING THE BOUNDARY (the guard
# `test_kir_boundary_to_the_product_is_a_closed_list` counted such by
# name). A resolution, not a registry entry: the crossing was REMOVED. The
# command in `tools/` remains a thin door and works letter for letter.
from kir.instruments.unwired_census import (                     # noqa: E402
    BY_CONSTRUCTION_REASONS, by_construction_reason, census, scan,
)


def _node(src: str) -> ast.AST:
    """The first definition in the source — the subject of the predicate."""
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return node
    raise AssertionError("в образце нет определения")


class ПредикатСпрашиваетСвойство(unittest.TestCase):
    """The kind is derived from a PROPERTY of the node, not from the spelling
    of the name (form 54)."""

    def test_протокол_узнаётся_по_базе_а_не_по_имени(self):
        # The name does NOT contain "Port" — it must be recognized by base.
        self.assertEqual(
            by_construction_reason(_node("""
                class ЧтоУгодно(Protocol):
                    def do(self) -> None: ...
            """)), "protocol")

    def test_имя_с_Port_но_без_базы_протоколом_НЕ_считается(self):
        # A DISTINGUISHING control: without it the predicate could match by
        # spelling, and the test above would pass for the wrong reason.
        self.assertIsNone(by_construction_reason(_node("""
            class ExecutionPort:
                pass
        """)))

    def test_валидатор_pydantic_узнаётся_по_декоратору(self):
        self.assertEqual(
            by_construction_reason(_node("""
                @model_validator(mode="after")
                def _проверка(self): return self
            """)), "pydantic_validator")

    def test_маршрут_требует_ВЫЗОВА_декоратора_с_путём(self):
        self.assertEqual(
            by_construction_reason(_node("""
                @app.post("/rpc")
                async def обработчик(request): ...
            """)), "route")
        # A bare `x.get` without a call is not a route but an ordinary
        # attribute.
        self.assertIsNone(by_construction_reason(_node("""
            @registry.get
            def обычная(): ...
        """)))

    def test_у_каждой_причины_есть_ТЕКСТ(self):
        """A kind without reasons becomes a dump where anything inconvenient
        is swept."""
        for key in ("protocol", "pydantic_validator", "route"):
            self.assertIn(key, BY_CONSTRUCTION_REASONS)
            self.assertGreater(len(BY_CONSTRUCTION_REASONS[key]), 30,
                               "причина обязана объяснять, а не называть")


class ПереписьРазличаетУстройствоОтДолга(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = census(host=pathlib.Path("/opt/kukai-rebuild1/backend"))
        cls.nikto = [r for r in cls.out["unwired"] if r["host"] == "никто"]

    def test_фикстур_чекера_в_никто_НОЛЬ(self):
        """The very false signal: they are called by the owner's own tests,
        and the scanner knows it."""
        fx = [r for r in self.nikto
              if "fixtures/builders" in r["sites"][0][0]]
        self.assertEqual(fx, [], "фикстуры чекера зовут тесты хозяина")

    def test_фикстуры_НЕ_исчезли_а_приписаны_тестам_хозяина(self):
        """Distinguishing: one can also leave "nobody" by silently vanishing.
        This is not that."""
        fx = [r for r in self.out["unwired"]
              if "fixtures/builders" in r["sites"][0][0]]
        self.assertEqual(len(fx), 16)
        self.assertEqual({r["host"] for r in fx}, {"тесты_хозяина"})

    def test_порты_названы_устройством_а_не_долгом(self):
        порты = [r for r in self.nikto if r["sites"][0][0] == "kir/ports.py"]
        self.assertTrue(порты, "порты обязаны остаться ВИДНЫ, а не исчезнуть")
        for row in порты:
            self.assertEqual(row["kind"], "по_построению")
            self.assertEqual(row["why"], "protocol")

    def test_валидаторы_профиля_названы_устройством(self):
        имена = {r["name"] for r in self.nikto if r["kind"] == "по_построению"}
        self.assertIn("_filter_and_suspension_are_exclusive", имена)
        self.assertIn("_nominal_cannot_become_load_bearing", имена)

    def test_по_построению_НЕ_поглотило_весь_список(self):
        """Degeneracy: a kind that has absorbed everything distinguishes no
        better than nothing."""
        по_построению = sum(1 for r in self.nikto if r["kind"] == "по_построению")
        self.assertGreater(по_построению, 0)
        self.assertLess(по_построению, len(self.nikto) // 4,
                        "род стал свалкой — проверь предикат")


class РазбивкаСчитаетТоЖеЧтоПоказывает(unittest.TestCase):
    """The main subject: the unit of measurement equals the unit of the
    report (form 24)."""

    @classmethod
    def setUpClass(cls):
        cls.text = subprocess.run(
            [sys.executable, "tools/unwired_census.py",
             "--host", "/opt/kukai-rebuild1/backend"],
            cwd=REPO, capture_output=True, text=True, timeout=900,
            env={"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"},
        ).stdout

    def test_заголовок_разбивки_НАЗЫВАЕТ_своё_подмножество(self):
        self.assertIn("РАЗБИВКА ПО МОДУЛЯМ — подмножество", self.text)
        self.assertIn("зовёт НИКТО", self.text)

    def test_builders_НЕ_печатается_в_разбивке(self):
        """The exact line that fooled two readers in a row."""
        разбивка = self.text.split("РАЗБИВКА ПО МОДУЛЯМ")[1]
        self.assertNotIn("fixtures/builders", разбивка)

    def test_честный_долг_меньше_общего_числа(self):
        # 🔴 ANCHOR — THE WHOLE LINE, NOT A SUBSTRING, AND THIS WAS PAID FOR
        # RIGHT HERE. The first edition took `split("called by nobody")` and
        # caught the HEADER PROSE ("dunders are excluded: they are called by
        # the runtime, called by name by nobody"), that is, it matched by
        # APPEARANCE instead of PLACE — precisely the form this whole file is
        # written against. Caught by a run, not by eyes.
        self.assertIn("ЧЕСТНЫЙ ДОЛГ:", self.text)
        долг = int(self.text.split("ЧЕСТНЫЙ ДОЛГ:")[1].split()[0])
        никто = None
        for line in self.text.splitlines():
            if line.strip().startswith("зовёт никто"):
                никто = int(line.split()[-1])
                break
        self.assertIsNotNone(никто, "строка счёта «зовёт никто» не найдена")
        self.assertLess(долг, никто, "устройство обязано быть ВЫЧТЕНО из долга")
        self.assertGreater(долг, никто // 2, "вычли слишком много — это не долг")


class НепрочитанныйФайлДисквалифицируетОтчёт(unittest.TestCase):
    """An unread module NARROWS the set of usages, that is, it INFLATES the
    debt."""

    def test_сломанный_файл_виден_и_назван(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            корень = pathlib.Path(tmp) / "pkg"
            (корень / "вложенный").mkdir(parents=True)
            (корень / "целый.py").write_text("def живое(): pass\n")
            (корень / "вложенный" / "битый.py").write_text("def (\n")
            seen = scan(корень)
            self.assertEqual(seen["unparsed"], ["pkg/вложенный/битый.py"])

    def test_на_целом_дереве_непрочитанного_НЕТ(self):
        """Distinguishing: the test above is green even when the instrument
        declares EVERYTHING broken."""
        self.assertEqual(census()["unparsed"], [])


if __name__ == "__main__":
    unittest.main()
