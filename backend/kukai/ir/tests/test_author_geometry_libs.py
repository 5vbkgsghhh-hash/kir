"""SHAPELY И NUMPY В АВТОРСКОМ СКРИПТЕ — ЗА ФЛАГОМ, ВЫКЛЮЧЕННЫМ ПО УМОЛЧАНИЮ.

ЗАЧЕМ ВООБЩЕ. Белый список песочницы — ровно `math`/`itertools`/`functools`,
поэтому автор всякий раз пишет своими руками offset полигона, выборку круга
ломаной и булевы операции: `course/recipes.py::_SILHOUETTE` содержит и
самодельную выборку круга, и собственный сертификат отклонения в миллиметрах.
При этом shapely и numpy УЖЕ живут в проде — `ir/design_check.py` и
`modeling/checker/*`, куда ведёт `live/verdict.py`; закрыты они только для
авторской песочницы.

ЧТО ДЕРЖИТ БЕЗОПАСНОСТЬ, КОГДА ФЛАГ ВКЛЮЧЁН. Не белый список — он и раньше не
был границей (см. §«ЧЕГО ЭТА ПЕСОЧНИЦА НЕ ДЕЛАЕТ» в `sandbox.py`). Держат слои
ОС: отдельный процесс, пространства имён, пустой корень, RLIMIT_FSIZE=0,
RLIMIT_NPROC=0, сетевое пространство без маршрутов. Расширение C — произвольный
машинный код в адресном пространстве ребёнка, и удержать его может ТОЛЬКО ядро.
Поэтому здесь проверяется не только «shapely заработал», но и что при
включённом флаге НИ ОДИН слой не ослаб: корень пуст, сети нет, писать нельзя.

ПОРЯДОК НАМЕРЕННЫЙ. Сначала отсутствие (флаг выключен ⇒ ничего не изменилось и
отказ типизирован), потом присутствие. Способность, включённая раньше, чем
доказано её отсутствие по умолчанию, — это способность, включённая всегда.

    venv/bin/python3.12 -m pytest kukai/ir/tests/test_author_geometry_libs.py -q
"""
from __future__ import annotations

import os
import unittest

from kukai.ir import diag, sandbox

#: Скрипт-эталон для доказательства «выключенный флаг ничего не сдвинул».
#: Дайджесты ниже сняты с кода ДО правки (`git show 15d5b206`), тем же
#: интерпретатором, тем же модулем языка. Подпись, которая «наверное та же», —
#: не подпись.
_PINNED_SOURCE = (
    'lvl = create_level(elev_mm=0, name="Этаж 1")\n'
    'create_wall(p0_mm=(0, 0), p1_mm=(5000, 0), level=lvl, height_mm=3000)\n'
)
_PINNED_AUTHOR_DIGEST = (
    "49ccb2790a1b7db67862458067270a7f2566faee8254ada3f746ebd41e7ae4e5")
_PINNED_PROGRAM_DIGEST = (
    "24c19929c1b7c95a0f73189287a12e562b91079584b061a78551f696d1436a93")

#: Политика ВЫКЛЮЧЕННОГО флага. Совпадает с прод-шлюзом ровно тогда, когда флаг
#: снят, и НЕ совпадает, когда поднят: `serving._sandbox_policy()` передаёт ещё
#: и `allowed_imports=allowed_imports_for_env()`, а здесь белый список заморожен
#: умолчанием класса. Прежняя редакция этой строки читалась как «ровно прод и
#: ничего больше» — прозой шире, чем кодом (форма 9): случаи с поднятым флагом
#: обязаны брать `live_policy()`, и они её и берут.
_PROD_POLICY = sandbox.SandboxPolicy(replay_check=True)

#: Контур считает shapely, плиту кладёт KIR. Образец, с которого списано, —
#: `tools/design/examples/contour_shapely.py`; там тот же расчёт живёт БЕЗ
#: песочницы, и это ровно тот разрыв, который флаг закрывает.
_CONTOUR_SCRIPT = '''
from shapely.geometry import LineString

spine = LineString([(0.0, 0.0), (30000.0, 4000.0), (60000.0, 0.0)])
ribbon = spine.buffer(7000.0, cap_style="flat", join_style="round")
simple = ribbon.simplify(250.0)
pts = [[round(float(x), 1), round(float(y), 1)]
       for x, y in simple.exterior.coords[:-1]]

# ПРИБЛИЖЕНИЕ, НАЗВАННОЕ ЧИСЛОМ. `simplify` обещает не больше допуска; сколько
# вышло на самом деле, знает только разность площадей к периметру.
drift = ribbon.symmetric_difference(simple).area / ribbon.exterior.length
print(f"контур: {len(ribbon.exterior.coords) - 1} вершин -> {len(pts)}, "
      f"отклонение {drift:.0f} мм")

lvl = create_level(elev_mm=0, name="Этаж 1")
create_floor_by_contour(contour={"outer": {"shape": "poly", "points_mm": pts}},
                        level=lvl, type="Монолит 200")
'''


class _FlagCase(unittest.TestCase):
    """Тумблер снимается ВСЕГДА: набор гоняется в случайном порядке."""

    def setUp(self) -> None:
        self._saved = os.environ.get(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG)
        os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)
        else:
            os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = self._saved

    def turn_on(self) -> None:
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"

    def live_policy(self) -> sandbox.SandboxPolicy:
        """Политика РОВНО как её строит прод-шлюз в этот момент."""
        from kukai.ir import serving
        return serving._sandbox_policy()


class TheFlagIsOffAndNothingMoved(_FlagCase):
    """ОТСУТСТВУЮЩЕЕ ОСТАЁТСЯ ОТСУТСТВУЮЩИМ."""

    def test_the_default_whitelist_is_untouched(self) -> None:
        self.assertFalse(sandbox.author_geometry_libs_enabled())
        self.assertEqual(sandbox.allowed_imports_for_env(),
                         sandbox.ALLOWED_IMPORTS)
        self.assertEqual(sandbox.ALLOWED_IMPORTS,
                         ("math", "itertools", "functools"))
        self.assertEqual(self.live_policy().allowed_imports,
                         sandbox.ALLOWED_IMPORTS)

    def test_the_flag_name_is_the_one_the_gate_reads(self) -> None:
        """Константа и литерал внутри калитки не могут разъехаться.

        Литерал там стоит не по недосмотру: `tools/capability_map.py` ищет
        флаги РЕГУЛЯРКОЙ по тексту, и вызов через константу инвентарь не
        увидел бы — флаг стал бы невидимым, то есть лежащим на складе по
        построению. Разъезд имён держит этот тест, а не договорённость.
        """
        self.assertEqual(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG,
                         "KUKAI_IR_AUTHOR_GEOMETRY_LIBS")
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"
        self.assertTrue(sandbox.author_geometry_libs_enabled())
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "0"
        self.assertFalse(sandbox.author_geometry_libs_enabled())

    def test_the_digests_of_an_untouched_script_did_not_move(self) -> None:
        """Подписи, снятые с кода ДО правки, обязаны совпасть до символа."""
        result = sandbox.execute_author_script(_PINNED_SOURCE,
                                               policy=_PROD_POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(result.author_digest, _PINNED_AUTHOR_DIGEST)
        self.assertEqual(result.program_digest, _PINNED_PROGRAM_DIGEST)

    def test_importing_shapely_is_a_typed_refusal_naming_the_line(self) -> None:
        """ПУТЬ ОТКАЗА. Сырой трейсбек наружу не выходит никогда."""
        source = ("lvl = create_level(elev_mm=0, name=\"Этаж 1\")\n"
                  "from shapely.geometry import Polygon\n")
        result = sandbox.execute_author_script(source, policy=_PROD_POLICY)
        self.assertFalse(result.ok)
        refusal = result.refusal
        self.assertEqual(refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertEqual(refusal.blame, "author")
        self.assertEqual(refusal.line, 2)
        self.assertEqual(refusal.line_text,
                         "from shapely.geometry import Polygon")
        self.assertIn("shapely.geometry", refusal.render())
        self.assertEqual(refusal.detail["allowed"],
                         list(sandbox.ALLOWED_IMPORTS))
        self.assertNotIn("Traceback", refusal.render())
        # Программа при отказе не выходит наружу вообще — половина программы
        # хуже отказа: она выглядит построенной.
        self.assertEqual(result.ops, [])

    def test_numpy_is_refused_the_same_way(self) -> None:
        result = sandbox.execute_author_script("import numpy\n",
                                               policy=_PROD_POLICY)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertEqual(result.refusal.line, 1)

    def test_a_submodule_of_a_non_package_is_still_refused(self) -> None:
        """Правило «подмодуль едет с ПАКЕТОМ» ничего не открыло в stdlib:
        `math` пакетом не является, и `math.foo` отказывает как отказывал."""
        result = sandbox.execute_author_script("import math.foo\n",
                                               policy=_PROD_POLICY)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)


class TheFlagIsOnAndTheContourIsComputed(_FlagCase):
    """ПРИСУТСТВИЕ: библиотека считает контур, KIR кладёт плиту."""

    def test_the_live_policy_widens_within_one_turn(self) -> None:
        """Тумблер читается ЖИВЬЁМ. Кэшированная политика означала бы, что
        «включил флаг» = «перезапусти четыре воркера»."""
        self.assertEqual(self.live_policy().allowed_imports,
                         sandbox.ALLOWED_IMPORTS)
        self.turn_on()
        widened = self.live_policy()
        self.assertEqual(widened.allowed_imports,
                         sandbox.ALLOWED_IMPORTS + sandbox.GEOMETRY_IMPORTS)
        # Изменилась РОВНО одна строчка политики. Ни один слой изоляции не
        # сдвинулся — это и есть «C-расширение держит ядро, а не белый список».
        default = sandbox.SandboxPolicy(replay_check=True)
        for name in ("network", "filesystem_isolation", "probe_network",
                     "replay_check", "memory_mb", "cpu_seconds",
                     "wall_seconds", "nofile", "max_ops"):
            self.assertEqual(getattr(widened, name), getattr(default, name),
                             f"флаг сдвинул слой изоляции: {name}")

    def test_shapely_computes_a_contour_and_kir_places_the_floor(self) -> None:
        """ГЛАВНЫЙ ТЕСТ ФАЙЛА: buffer -> упрощение -> create_floor_by_contour."""
        self.turn_on()
        result = sandbox.execute_author_script(_CONTOUR_SCRIPT,
                                               policy=self.live_policy())
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        ops = [op["op"] for op in result.ops]
        self.assertEqual(ops, ["create_level", "create_floor_by_contour"])

        floor = result.ops[1]
        points = floor["contour"]["outer"]["points_mm"]
        self.assertEqual(floor["contour"]["outer"]["shape"], "poly")
        self.assertGreaterEqual(len(points), 4)
        # Числа, а не объекты: программа IR обязана быть представима в JSON.
        for point in points:
            self.assertEqual(len(point), 2)
            for value in point:
                self.assertIsInstance(value, float)
        # Отклонение НАЗВАНО числом и доехало до квитанции этого же хода.
        self.assertIn("отклонение", result.stdout)
        self.assertIn("мм", result.stdout)

    def test_the_price_is_paid_only_by_the_script_that_names_it(self) -> None:
        """Прогрев решает ИСХОДНИК. Скрипт, не назвавший shapely, платить не
        обязан: +536 мс и +43 МБ на запуск, а скрипт исполняется ДВАЖДЫ."""
        self.turn_on()
        policy = self.live_policy()

        silent = sandbox.execute_author_script(_PINNED_SOURCE, policy=policy)
        self.assertTrue(silent.ok, silent.refusal and silent.refusal.render())
        self.assertEqual(silent.isolation["warmed_libs"], [])

        loud = sandbox.execute_author_script(_CONTOUR_SCRIPT, policy=policy)
        self.assertTrue(loud.ok, loud.refusal and loud.refusal.render())
        # Подмодуль греется потому, что его НАЗВАЛ исходник: `import shapely`
        # тянет `shapely.geometry`, но не `shapely.ops`, а после chroot диска
        # уже нет — ненайденный подмодуль стал бы отказом не по адресу.
        self.assertIn("shapely", loud.isolation["warmed_libs"])
        self.assertIn("shapely.geometry", loud.isolation["warmed_libs"])
        self.assertGreater(loud.peak_rss_kb, silent.peak_rss_kb)

    def test_the_program_is_signed_together_with_the_library_it_used(self) -> None:
        """Библиотека, посчитавшая контур, НАЗВАНА ВЕРСИЕЙ в той же квитанции.

        Это вторая половина ответа на «одно здание, две подписи»: расширять
        белый список, не подписывая среду, значило бы построить ту самую дыру
        в полный рост.
        """
        self.turn_on()
        result = sandbox.execute_author_script(_CONTOUR_SCRIPT,
                                               policy=self.live_policy())
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        rows = {m["name"]: m for m in result.environment["modules"]}
        self.assertEqual(sorted(rows),
                         sorted(sandbox.ALLOWED_IMPORTS
                                + sandbox.GEOMETRY_IMPORTS))
        self.assertEqual(rows["shapely"]["via"], "importlib.metadata")
        self.assertRegex(rows["shapely"]["version"], r"^\d+\.\d+")
        self.assertTrue(rows["shapely"]["loaded"])
        # GEOS дрейфует ОТДЕЛЬНО от shapely и подписывается отдельно.
        self.assertIn("geos_version", rows["shapely"]["native"])

        from kukai.ir import serving
        receipt = serving._authorship_receipt(
            result, source_bytes=len(_CONTOUR_SCRIPT.encode("utf-8")))
        self.assertEqual(receipt["environment"]["digest"], result.env_digest)

    def test_no_isolation_layer_was_relaxed(self) -> None:
        """ЗАМЕР, А НЕ ОБЕЩАНИЕ: при включённом флаге и загруженном shapely
        корень по-прежнему пуст, сети нет, писать нельзя, форкать нельзя."""
        self.turn_on()
        policy = self.live_policy()

        # Слои снимаются с УСПЕШНОГО запуска, который shapely действительно
        # загрузил: измерять изоляцию на ходе, где библиотеки нет, значило бы
        # измерять не то.
        built = sandbox.execute_author_script(_CONTOUR_SCRIPT, policy=policy)
        self.assertTrue(built.ok, built.refusal and built.refusal.render())
        self.assertIn("shapely", built.isolation["warmed_libs"])
        isolation = built.isolation
        self.assertEqual(isolation["namespaces"], "user+mount+net")
        self.assertEqual(isolation["filesystem"], "chroot")
        self.assertTrue(isolation["network_probe"].startswith("unreachable"))
        self.assertEqual(isolation["limits"]["RLIMIT_FSIZE"], 0)
        self.assertEqual(isolation["limits"]["RLIMIT_NPROC"], 0)
        self.assertEqual(isolation["limits"]["RLIMIT_CORE"], 0)

        # И ограниченные builtins тоже на месте: `open` остаётся заглушкой,
        # объясняющей ПОЧЕМУ его нет. Наследник BaseException намеренно —
        # `except Exception` в скрипте не должен его проглатывать.
        probe = _CONTOUR_SCRIPT + 'open("/etc/passwd")\n'
        blocked = sandbox.execute_author_script(probe, policy=policy)
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.refusal.code, diag.SANDBOX_FORBIDDEN_BUILTIN)
        self.assertEqual(blocked.refusal.detail["name"], "open")
        self.assertEqual(blocked.isolation["filesystem"], "chroot")

    def test_a_module_outside_the_widened_list_is_still_refused(self) -> None:
        """Список расширен ровно на две библиотеки, а не «на внешние модули»."""
        self.turn_on()
        result = sandbox.execute_author_script("import networkx\n",
                                               policy=self.live_policy())
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertEqual(result.refusal.detail["allowed"],
                         list(sandbox.ALLOWED_IMPORTS
                              + sandbox.GEOMETRY_IMPORTS))


if __name__ == "__main__":
    unittest.main()
