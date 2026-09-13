"""TWO NAMES FOR ONE QUANTITY — AND PROD ANSWERED "NOT INSTALLED" WHILE BEING INSTALLED.

🔴 MEASURED 03.09.2026, ON LIVE PROD. The `kir/__init__.py` docstring itself
names this defect by name ("two names for one quantity") and itself says it
is only caught by a run IN THE INSTALLATION. There was no run in the
installation, and the defect lived on:

    prod-venv:  dist-info `kir 0.1.0`   (a name that has not been in
                pyproject since 31.08)
    the code asks for `kir-building`  ->  PackageNotFoundError
    kir.__version__ = «не установлен (запуск из дерева)»   <- a lie, it IS installed

The cost turned out NOT to be in the answer itself — the receipt does not
carry the version, there are three readers of it. The cost showed up at a
neighbor: `kukai/model_repository.kir_runtime_identity` asks for
`version("kir-building")`, falls back to `kir.__version__` on refusal, and
that string is IN RUSSIAN and fails `isascii()` — and the runtime version in
KUKAI's identity became `"source-tree"`. After fixing the carrier:
`('0.4.0', <digest>)`.

WHY THE GUARD LOOKS AT THE DISTRIBUTION MAP, NOT AT `__version__`. Asking
"name your version" is not enough: from a BARE TREE the honest answer is
"not installed", and the guard would either always go red or always stay
silent on it. What actually discriminates is exactly one thing: WHO
declares the top-level module `kir`. Measured on both installs (an
editable prod and a clean one from PyPI) — `packages_distributions()["kir"]`
sees the editable one too, i.e. the question can be asked wherever the
package is installed.

THE THIRD LINK — BUILD LEFTOVERS IN THE TREE. A `*.egg-info` next to the
package answers the same question with ITS OWN number for anyone who has
the tree on `sys.path`, and silently beats the real install. On the day of
the measurement there were two of them: `kir.egg-info` 0.1.0 (a dead name)
and `kir_building.egg-info` 0.3.0 while `pyproject` said 0.4.0 — and the
second one steered MY OWN artifact measurement one number sideways.
"""
from __future__ import annotations

import importlib.metadata as метаданные
import pathlib
import unittest
from collections.abc import Mapping, Sequence

import kir

#: The name the code asks for. The sole carrier is `kir/__init__.py`.
СВОЁ_ИМЯ = kir._DIST
ВЕРХНИЙ_МОДУЛЬ = "kir"


def чужие_объявители(карта: Mapping[str, Sequence[str]], модуль: str,
                     своё: str) -> list[str]:
    """Who, OTHER THAN its own distribution, declares the top-level module `модуль`.

    A pure function: the subject arrives as an argument, so the control
    with a substituted map checks it too. An instrument nothing can turn
    red guards nothing.
    """
    return sorted(имя for имя in карта.get(модуль, ()) if имя != своё)


class ОдноИмяДистрибутива(unittest.TestCase):

    def test_верхний_модуль_объявляет_ровно_один_дистрибутив(self) -> None:
        карта = метаданные.packages_distributions()
        объявители = карта.get(ВЕРХНИЙ_МОДУЛЬ)
        if not объявители:
            self.skipTest(
                "пакет не установлен в этот интерпретатор (голое дерево) — "
                "вопрос «кто объявляет kir» здесь не задаваем")
        лишние = чужие_объявители(карта, ВЕРХНИЙ_МОДУЛЬ, СВОЁ_ИМЯ)
        self.assertEqual(
            лишние, [],
            f"верхний модуль `{ВЕРХНИЙ_МОДУЛЬ}` объявляют {объявители}, а код "
            f"спрашивает `{СВОЁ_ИМЯ}`: лишние дистрибутивы {лишние}. "
            "Снять: `pip uninstall <лишнее имя>` в этой установке")
        self.assertIn(
            СВОЁ_ИМЯ, объявители,
            f"код спрашивает `{СВОЁ_ИМЯ}`, а модуль объявлен как {объявители}")

    def test_контроль_подложенная_карта_краснеет(self) -> None:
        """Both sides: a foreign name is caught, its own is not."""
        своя = {"kir": [СВОЁ_ИМЯ]}
        смесь = {"kir": ["kir", СВОЁ_ИМЯ]}
        self.assertEqual(чужие_объявители(своя, "kir", СВОЁ_ИМЯ), [])
        self.assertEqual(чужие_объявители(смесь, "kir", СВОЁ_ИМЯ), ["kir"],
                         "сторож не увидел бы ровно того дефекта, что был "
                         "в проде 03.09: dist-info под мёртвым именем `kir`")

    def test_имя_в_pyproject_и_имя_в_коде_одно(self) -> None:
        корень = pathlib.Path(kir.__file__).resolve().parent.parent
        pyproject = корень / "pyproject.toml"
        if not pyproject.is_file():
            self.skipTest("pyproject.toml рядом с пакетом нет — установка "
                          "из колеса, второй стороны сверки не существует")
        import tomllib
        объявлено = tomllib.loads(pyproject.read_text("utf-8"))["project"]["name"]
        self.assertEqual(
            объявлено, СВОЁ_ИМЯ,
            f"pyproject объявляет `{объявлено}`, код спрашивает `{СВОЁ_ИМЯ}` — "
            "это и есть «два имени одной величины»")

    def test_остатков_сборки_рядом_с_деревом_нет(self) -> None:
        """`*.egg-info` answers with ITS OWN number for anyone who has the tree on the path."""
        корень = pathlib.Path(kir.__file__).resolve().parent.parent
        if not (корень / "pyproject.toml").is_file():
            self.skipTest("не дерево разработки — остаткам сборки взяться "
                          "неоткуда")
        #: 🔴 THE DENOMINATOR. A walk that lost the root finds ZERO
        #: leftovers and reads as "clean" — so first it is declared how
        #: many names the walk MUST see, and only then are the leftovers
        #: counted.
        всё = sorted(p.name for p in корень.glob("*"))
        self.assertGreaterEqual(
            len(всё), 10,
            f"обход потерял предмет: в корне дерева KIR ({корень}) заведомо "
            f"больше десяти имён, а увидено {len(всё)}")
        остатки = [имя for имя in всё if имя.endswith(".egg-info")]
        self.assertEqual(
            остатки, [],
            f"в корне дерева лежат остатки сборки {остатки}: они объявляют "
            "версию СВОЮ и побеждают установку у всякого, чей cwd — дерево. "
            "Снять: rm -rf <имя>.egg-info (пересоздаётся сборкой)")


if __name__ == "__main__":
    unittest.main()
