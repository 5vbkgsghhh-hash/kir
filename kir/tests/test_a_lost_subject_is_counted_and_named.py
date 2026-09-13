"""A LOST SUBJECT MUST BE COUNTED AND NAMED, NOT SWALLOWED.

🔴 ONE SPECIES IN EIGHT PLACES, MEASURED 04.09.2026. Five instruments in
the `kir/instruments` catalog carried the same shape: an unread file, a
corrupt line, a damaged index disappeared FROM BOTH BASKETS AT ONCE — from
the numerator and from the denominator. The share then IMPROVED FROM DATA
LOSS, and the report on the remainder looked like a complete census.

What was measured BEFORE the fix. Numbers were taken at revision `4c9d546`
and re-measured on `3671b56` WITH THE PROD VENV
(`/opt/kukai-rebuild1/backend/venv/bin/python`, where `kir` is installed
editable from /opt/kir) — the same. The subject was checked by the first
line of each probe: `assert kir.__file__.startswith("/opt/kir")`.

    RT-08  bounds_audit  a 400 mm² ring — LEGITIMATE (`geom.MIN_RING_AREA_MM2`
           = 100.0) — was reported as rejected 1 of 1: the report line
           carried a number rewritten to "«>= 10000 мм²»", that is, a
           CENTURY-OLD law (the threshold was lowered on 21.08, see
           test_opening.py:711)
    RT-09  bounds_audit  lines counting traversal cells — ZERO; the outcome
           was taken from the exception TEXT, and a room with an
           unfamiliar failure walked away via `continue` out of the
           denominator of BOTH neighboring boundaries
    RT-10  bounds_audit  three corrupt L0 lines — "1 element" and not a
           word about the three
    RT-11  scope_audit   `[x for x in ()]` + `return x` -> 0 findings, a
           live call -> NameError. The comprehension's target and the
           `except ... as e` name were credited to the WHOLE function
    RT-12  scope_audit   an unreadable, unparseable file -> `находок: 0`,
           EXIT=0, not a word about the two lost
    RT-13  walk_denominator  two IDENTICAL traversals without a
           denominator, one file broken -> debt of 1 instead of 2. The
           debt ratchet would be closed BY CORRUPTION
    RT-15  relift_offline    a damaged index -> None, a missing one ->
           None: indistinguishable, and the corruption read as "the stage
           did not run"
    RT-19  decision_changes  a 6-line feed -> 5 read, the loss silent;
           on top of that `[1,2,3]` was counted alongside actual records

Every case here has a CONTROL: the same instrument on an input WITHOUT
corruption must stay silent. An instrument that always screams is no
different from a broken one.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from kir import contour as _contour
from kir import geom as _geom
from kir import mesh as _mesh
from kir.decompile import lift as _lift
from kir.instruments import bounds_audit as BA
from kir.instruments import decision_changes as DC
from kir.instruments import relift_offline as RO
from kir.instruments import scope_audit as SA
from kir.instruments import walk_denominator as WD


# ─────────────────────────── shared rig ──────────────────────────────────────

def _ring(area_mm2: float) -> list[list[float]]:
    """A square of a given area — the profile's ring."""
    side = area_mm2 ** 0.5
    return [[0.0, 0.0], [side, 0.0], [side, side], [0.0, side]]


def _dump(root: pathlib.Path, *, ring_area_mm2: float = 400.0,
          broken_lines: int = 0, rooms: list | None = None) -> pathlib.Path:
    """A synthetic decompile: L0 + a side index of profiles."""
    root.mkdir(parents=True, exist_ok=True)
    header = {"record": "header", "document": {
        "doc_name": "проба-потери",
        "levels": [{"id": "1", "name": "L1", "elevation_mm": 0.0}],
        "rooms": rooms or [], "grids": []}}
    lines = [json.dumps(header, ensure_ascii=False),
             json.dumps({"record": "element", "element": {
                 "element_id": "w1", "category": "OST_Walls",
                 "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [3000.0, 0.0, 0.0],
                 "level_id": "1", "level_name": "L1", "params": {}}},
                 ensure_ascii=False)]
    for i in range(broken_lines):
        lines.append('{"record": "element", "element": {ОБРЫВ %d' % i)
    (root / "L0.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "sketch.index.json").write_text(
        json.dumps({"profile_index": {"f1": {
            "profile_available": True,
            "exterior_loop": _ring(ring_area_mm2), "holes": []}}}),
        encoding="utf-8")
    return root


class ГраницаСпрашиваетсяУИмени(unittest.TestCase):
    """RT-08. A number next to a name goes stale; the name IS the address."""

    def _площадь(self, area_mm2: float):
        with tempfile.TemporaryDirectory() as tmp:
            d = _dump(pathlib.Path(tmp) / "разбор", ring_area_mm2=area_mm2)
            return BA.measure_dump(BA.Dump(d))["geom.MIN_RING_AREA_MM2"]

    def test_законное_кольцо_не_объявляется_отвергнутым(self) -> None:
        """EXACTLY THAT: 400 mm² against a threshold of 100 mm² — legitimate."""
        self.assertLess(_geom.MIN_RING_AREA_MM2, 400.0,
                        "проба перестала быть законной — перечитай порог")
        res = self._площадь(400.0)
        self.assertEqual(res.denominator, 1)
        self.assertEqual(res.rejected, 0,
                         "прибор отвергает кольцо, которое компилятор примет")
        self.assertIn(f"{_geom.MIN_RING_AREA_MM2:g} мм²", res.bound_repr)
        self.assertNotIn("10000", res.bound_repr,
                         "в строке отчёта осталось снятое 21.08 значение")

    def test_КОНТРОЛЬ_кольцо_ниже_живого_порога_отвергается(self) -> None:
        """Narrowness: the instrument must go red on a REAL violation."""
        res = self._площадь(_geom.MIN_RING_AREA_MM2 / 4.0)
        self.assertEqual(res.rejected, 1)

    def test_прибор_едет_за_ИМЕНЕМ_а_не_помнит_число(self) -> None:
        """FAIL CONTROL for the fix itself: the name moved — the
        instrument moved with it.

        The previous version would have passed this test ONLY by
        accident: it compared against the number written alongside, and did
        not react to a name substitution at all.
        """
        with mock.patch.object(_geom, "MIN_RING_AREA_MM2", 1_000_000.0):
            self.assertEqual(self._площадь(400.0).rejected, 1,
                             "порог подняли — прибор обязан это увидеть")
        # And in the reverse direction too, otherwise "tracks the name" is
        # only half proven: an instrument that is always red would pass
        # half of this check for free.
        with mock.patch.object(_geom, "MIN_RING_AREA_MM2", 4.0):
            self.assertEqual(self._площадь(50.0).rejected, 0,
                             "порог опустили — прибор обязан это увидеть")

    def test_соседний_ряд_координат_называет_живое_значение(self) -> None:
        """A second instance of the same species in the same file:
        `mesh._COORD_MAX_MM` was printed as "«<= 10 000 000»", the live
        value is 16 000 000."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _dump(pathlib.Path(tmp) / "разбор")
            out = BA.measure_dump(BA.Dump(d))
        self.assertIn(f"{_mesh._COORD_MAX_MM:.0f}",
                      out["mesh._COORD_MAX_MM"].bound_repr)
        self.assertIn(f"{_contour.MAX_ARC_BULGE:g}",
                      out["contour.MAX_ARC_BULGE"].bound_repr)


class НеизмеримоеНеВыдаётсяЗаЗамер(unittest.TestCase):
    """RT-09. The row about traversal cells counted NOT A SINGLE one."""

    _КОМНАТА_ОБЫЧНАЯ = {"name": "обычная", "boundary_loops_mm": [
        [[0.0, 0.0], [4000.0, 0.0], [4000.0, 3000.0], [0.0, 3000.0]]]}
    _КОМНАТА_БЮДЖЕТ = {"name": "вытянутая", "boundary_loops_mm": [
        [[0.0, 0.0], [3_000_000.0, 0.0], [3_000_000.0, 30.0], [0.0, 30.0]]]}

    def _мера(self, rooms):
        with tempfile.TemporaryDirectory() as tmp:
            d = _dump(pathlib.Path(tmp) / "разбор", rooms=rooms)
            return BA.measure_dump(BA.Dump(d))

    def test_ряд_объявляет_что_величина_не_измеряется(self) -> None:
        out = self._мера([self._КОМНАТА_ОБЫЧНАЯ, self._КОМНАТА_БЮДЖЕТ])
        res = out["lift._ROOM_INTERIOR_MAX_CELLS"]
        self.assertTrue(res.unmeasured, "ряд молчит о своей неизмеримости")
        self.assertEqual((res.denominator, res.rejected), (2, 1))
        self.assertIn(str(_lift._ROOM_INTERIOR_MAX_CELLS), res.bound_repr,
                      "предел спрашивается у имени, а не переписан числом")

    def test_КОНТРОЛЬ_настоящий_замер_неизмеримым_не_объявлен(self) -> None:
        """Narrowness: the neighboring row DOES MEASURE the quantity, and has no caveat."""
        out = self._мера([self._КОМНАТА_ОБЫЧНАЯ])
        self.assertFalse(out["geom.MIN_RING_AREA_MM2"].unmeasured)

    def test_отчёт_говорит_о_неизмеримости_ДО_чисел(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = _dump(pathlib.Path(tmp) / "разбор",
                      rooms=[self._КОМНАТА_БЮДЖЕТ])
            буфер = io.StringIO()
            with contextlib.redirect_stdout(буфер):
                BA.print_measurement([d])
        текст = буфер.getvalue()
        self.assertIn("ВЕЛИЧИНА НЕ ИЗМЕРЯЕТСЯ", текст)
        строки = текст.splitlines()
        глава = next(i for i, s in enumerate(строки)
                     if "lift._ROOM_INTERIOR_MAX_CELLS" in s)
        оговорка = next(i for i, s in enumerate(строки[глава:], глава)
                        if "ВЕЛИЧИНА НЕ ИЗМЕРЯЕТСЯ" in s)
        число = next(i for i, s in enumerate(строки[глава:], глава)
                     if "ОТВЕРГНУТО ВСЕГО" in s)
        self.assertLess(оговорка, число,
                        "оговорка обязана стоять ДО числа, а не под ним")

    def test_комната_с_НЕЗНАКОМЫМ_отказом_не_исчезает(self) -> None:
        """Here stood a `continue`, and the room vanished from both denominators."""
        def отказ_третьего_рода(exterior, holes):
            raise RuntimeError("отказ, которого прибор не знает")

        with mock.patch.object(_lift, "_room_interior_point",
                               отказ_третьего_рода):
            out = self._мера([self._КОМНАТА_ОБЫЧНАЯ, self._КОМНАТА_БЮДЖЕТ])
        потеря = out["room lift: отказ ДРУГОГО рода"]
        self.assertEqual((потеря.denominator, потеря.rejected), (2, 2))

    def test_КОНТРОЛЬ_знакомые_отказы_в_ряд_потери_не_попадают(self) -> None:
        out = self._мера([self._КОМНАТА_ОБЫЧНАЯ, self._КОМНАТА_БЮДЖЕТ])
        потеря = out["room lift: отказ ДРУГОГО рода"]
        self.assertEqual((потеря.denominator, потеря.rejected), (2, 0))


class БитаяСтрокаРазбораПосчитана(unittest.TestCase):
    """RT-10. `except Exception: continue` inside the L0 read."""

    def test_битые_строки_названы_числом_и_номером(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = _dump(pathlib.Path(tmp) / "разбор", broken_lines=3)
            dump = BA.Dump(d)
            буфер = io.StringIO()
            with contextlib.redirect_stdout(буфер):
                BA.print_measurement([d])
        self.assertEqual(len(dump.broken_lines), 3)
        self.assertEqual(sorted(dump.broken_lines), [3, 4, 5])
        self.assertIn("НЕ ПРОЧЛИСЬ: 3", буфер.getvalue())

    def test_КОНТРОЛЬ_целый_разбор_о_потере_молчит(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = _dump(pathlib.Path(tmp) / "разбор")
            dump = BA.Dump(d)
            буфер = io.StringIO()
            with contextlib.redirect_stdout(буфер):
                BA.print_measurement([d])
        self.assertEqual(dump.broken_lines, {})
        self.assertNotIn("НЕ ПРОЧЛИСЬ", буфер.getvalue())

    def test_строка_заявленная_элементом_без_элемента_посчитана(self) -> None:
        """Before, this was a `KeyError` in the middle of the read — the other end of the road."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _dump(pathlib.Path(tmp) / "разбор")
            путь = d / "L0.jsonl"
            путь.write_text(
                путь.read_text(encoding="utf-8")
                + '{"record": "element"}\n', encoding="utf-8")
            dump = BA.Dump(d)
        self.assertEqual(len(dump.broken_lines), 1)
        self.assertEqual(len(dump.elements), 1)


class ИмяСвязаноТамГдеЕгоСвязали(unittest.TestCase):
    """RT-11. A comprehension and `except as` each have THEIR OWN scope.

    The expectation is checked by EXECUTION, not by reasoning: Python is
    the arbiter here.
    """

    #: (name, source, expected findings, whether a live call fails)
    СЛУЧАИ = (
        ("цель comprehension после выражения",
         "def f():\n    [x for x in ()]\n    return x\n", [(3, "x")], True),
        ("КОНТРОЛЬ: внутри выражения цель видна",
         "def f():\n    return [x + 1 for x in ()]\n", [], False),
        ("словарное выражение — та же область",
         "def f():\n    {k: v for k, v in ()}\n    return k\n",
         [(3, "k")], True),
        ("морж внутри выражения выходит наружу (PEP 572)",
         "def f():\n    [(y := i) for i in (1,)]\n    return y\n", [], False),
        ("except as e: чтение ПОСЛЕ обработчика",
         "def f():\n    try:\n        pass\n    except OSError as e:\n"
         "        pass\n    return e\n", [(6, "e")], True),
        ("КОНТРОЛЬ: внутри обработчика имя видно",
         "def f():\n    try:\n        raise OSError('и')\n"
         "    except OSError as e:\n        return str(e)\n", [], False),
        ("вложенные for одного выражения",
         "def f():\n    return [c for row in ((1,),) for c in row]\n",
         [], False),
    )

    def test_прибор_и_питон_говорят_одно(self) -> None:
        for имя, код, ждём, падает in self.СЛУЧАИ:
            with self.subTest(имя):
                self.assertEqual(SA.unbound_names(код), ждём)
                область: dict = {}
                exec(compile(код, "<проба>", "exec"), область)   # noqa: S102
                if падает:
                    with self.assertRaises(NameError):
                        область["f"]()
                else:
                    область["f"]()

    def test_КОНТРОЛЬ_обычное_связывание_не_стало_находкой(self) -> None:
        """Narrowness of the fix: it removed a false SILENCE, not introduced a false alarm."""
        self.assertEqual(SA.unbound_names(
            "def f():\n    xs = [1]\n    return [x for x in xs]\n"), [])
        self.assertEqual(SA.unbound_names(
            "def f(items):\n"
            "    return {k: v for k, v in items if k}\n"), [])


class НепрочитанныйФайлНеУменьшаетКорпус(unittest.TestCase):
    """RT-12 and RT-13. Two traversals, one shape: a mute `continue`."""

    @staticmethod
    @contextlib.contextmanager
    def _корень(*, порча: bool):
        """A tree of one healthy file and (on demand) two corrupted ones.

        Unreadable means a DANGLING SYMLINK: it gives `OSError` to both a
        regular user and root, whereas `chmod 000` would still open under
        root and the control would go green incorrectly (a lesson from a
        neighbor, 30.08.2026).
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "пакет"
            root.mkdir()
            (root / "test_здоровый.py").write_text(
                "import pathlib\n"
                "def test_обход(self):\n"
                "    x = [p.read_text() for p in "
                "pathlib.Path('.').rglob('*.py')]\n"
                "    self.assertEqual(x, [])\n", encoding="utf-8")
            if порча:
                os.symlink("НЕТ-ТАКОГО-ФАЙЛА", root / "test_нечитаемый.py")
                (root / "test_битый.py").write_text(
                    "import pathlib\n"
                    "def test_обход(self):\n"
                    "    x = [p.read_text() for p in "
                    "pathlib.Path('.').rglob('*.py')]\n"
                    "    self.assertEqual(x, [])\n"
                    "def сломано(:\n", encoding="utf-8")
            yield root

    def test_scope_audit_называет_непрочитанное(self) -> None:
        with self._корень(порча=True) as root:
            ведомость: dict = {}
            hits, _ = SA.audit(root, refusals=ведомость)
        self.assertEqual(len(ведомость), 2, ведомость)
        причины = " ".join(ведомость.values())
        self.assertIn("НЕ ПРОЧЁЛСЯ", причины)
        self.assertIn("НЕ РАЗОБРАЛСЯ", причины)

    def test_scope_audit_без_ведомости_КРАСНЕЕТ(self) -> None:
        """The instrument has no right to silently return a number while losing a file."""
        with self._корень(порча=True) as root:
            with self.assertRaises(SA.AuditIncomplete):
                SA.audit(root)

    def test_КОНТРОЛЬ_целый_корень_проходит_молча(self) -> None:
        with self._корень(порча=False) as root:
            ведомость: dict = {}
            SA.audit(root, refusals=ведомость)
            SA.audit(root)                     # there must be no refusal
        self.assertEqual(ведомость, {})

    def test_перепись_обходов_не_теряет_сломанный_файл(self) -> None:
        """Both files are traversals WITHOUT a denominator; one is broken.

        Before, the debt came out as 1 instead of 2, that is, CORRUPTION
        was closing the debt.
        """
        with self._корень(порча=True) as root:
            ведомость: dict = {}
            с, без = WD.перепись(root, непрочитанные=ведомость)
        self.assertEqual(len(без), 1, без)
        self.assertEqual(len(ведомость), 2, ведомость)
        self.assertTrue(any("test_битый.py" in p for p in ведомость))

    def test_перепись_без_ведомости_КРАСНЕЕТ(self) -> None:
        with self._корень(порча=True) as root:
            with self.assertRaises(WD.ПереписьНеполна):
                WD.перепись(root)

    def test_КОНТРОЛЬ_целая_перепись_молчит(self) -> None:
        with self._корень(порча=False) as root:
            ведомость: dict = {}
            с, без = WD.перепись(root, непрочитанные=ведомость)
            WD.перепись(root)                  # there must be no refusal
        self.assertEqual(ведомость, {})
        self.assertEqual((len(с), len(без)), (0, 1))


class ПорчаОтличаетсяОтОтсутствия(unittest.TestCase):
    """RT-15. `except (OSError, ValueError): return None` for both outcomes."""

    @staticmethod
    @contextlib.contextmanager
    def _разбор(*, порча: bool):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "sketch.index.json").write_text('{"a": 1}', encoding="utf-8")
            (d / "curtain.index.json").write_text(
                '{"a": 1' if порча else '{"a": 1}', encoding="utf-8")
            yield d

    ИМЕНА = ("sketch.index.json", "curtain.index.json", "tag.index.json")

    def test_три_исхода_различены_тремя_ответами(self) -> None:
        with self._разбор(порча=True) as d:
            здоровый = RO._load_envelope(d, "sketch.index.json")
            отсутствующий = RO._load_envelope(d, "tag.index.json")
            with self.assertRaises(RO.SideIndexUnreadable):
                RO._load_envelope(d, "curtain.index.json")
            битый_с_ведомостью: dict = {}
            RO._load_envelope(d, "curtain.index.json",
                              refusals=битый_с_ведомостью)
            назван = RO.unreadable_side_indexes(d, self.ИМЕНА)
            нет_рядом = RO.absent_side_indexes(d, self.ИМЕНА)
        self.assertEqual(здоровый, {"a": 1})
        self.assertIsNone(отсутствующий)
        self.assertEqual(list(битый_с_ведомостью), ["curtain.index.json"])
        self.assertEqual(list(назван), ["curtain.index.json"])
        self.assertEqual(list(нет_рядом), ["tag.index.json"],
                         "отсутствие и порча обязаны отвечать РАЗНЫМ спутником")

    def test_КОНТРОЛЬ_целые_индексы_отказа_не_дают(self) -> None:
        with self._разбор(порча=False) as d:
            self.assertEqual(RO.unreadable_side_indexes(d, self.ИМЕНА), {})
            self.assertEqual(RO._load_envelope(d, "curtain.index.json"),
                             {"a": 1})

    def test_каталога_нет_вовсе_отвечает_спутник_отсутствия(self) -> None:
        """One fact — one voice: `absent_*` is what speaks about "the directory does not exist"."""
        нет = pathlib.Path(tempfile.gettempdir()) / "нет-такого-разбора-rtD"
        ответ = RO.unreadable_side_indexes(нет, self.ИМЕНА)
        self.assertEqual(list(ответ), [""])
        self.assertIn("каталога разбора нет", ответ[""])


class БитаяСтрокаЛентыПосчитана(unittest.TestCase):
    """RT-19. `except ValueError: continue` in the feed read."""

    def setUp(self) -> None:
        DC._BROKEN_LINES.clear()

    tearDown = setUp

    def _лента(self, tmp: str, *, порча: bool) -> pathlib.Path:
        целые = [{"turn_id": f"t{i}", "code": "KIR-G101",
                  "ts": "2026-09-04"} for i in range(4)]
        строки = [json.dumps(r) for r in целые]
        if порча:
            строки.insert(2, '{"turn_id": "t9", "code": ОБРЫВ')
            строки.append("[1, 2, 3]")
        путь = pathlib.Path(tmp) / "kir_rejections.jsonl"
        путь.write_text("\n".join(строки) + "\n", encoding="utf-8")
        return путь

    def test_битые_строки_названы_файлом_и_номером(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            строки = DC._read(self._лента(tmp, порча=True))
        битые = DC.broken_feed_lines()["kir_rejections.jsonl"]
        self.assertEqual(len(строки), 4,
                         "не-запись `[1,2,3]` шла в счёт наравне с записями")
        self.assertEqual(sorted(битые), [3, 6])

    def test_КОНТРОЛЬ_целая_лента_потерь_не_даёт(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            строки = DC._read(self._лента(tmp, порча=False))
        self.assertEqual(len(строки), 4)
        self.assertEqual(DC.broken_feed_lines(), {})


class ПриборНеСтановитсяОбходомБезЗнаменателя(unittest.TestCase):
    """This file itself has no right to move someone else's ratchet.

    The `walk_denominator` census counts as a traversal any file that has
    BOTH a tree search AND a source read. Here there is neither `rglob`,
    nor `iterdir`, nor `ast.walk` — and this is checked, not promised: a
    test that quietly became a traversal would paint
    `test_a_walk_declares_its_denominator` red with someone else's redness.
    """

    def test_этот_файл_обходом_не_считается(self) -> None:
        текст = pathlib.Path(__file__).read_text(encoding="utf-8")
        self.assertFalse(WD.это_обход(ast.parse(текст)))


if __name__ == "__main__":
    unittest.main()
