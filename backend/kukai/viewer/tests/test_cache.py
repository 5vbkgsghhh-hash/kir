"""КЭШ СЦЕНЫ: холодное открытие платит первый, а не каждый.

ЗАМЕР 11.08.2026, `демо-v3` со слоем графа, ПО ЭТАПАМ (19.7 с в том прогоне):

    L0 #1 (read_decompile)            4.45 с   22.6 %
    L1 (tree.json)                    3.60 с   18.3 %
    graph_from_l0                     3.28 с   16.6 %
    L0 #2 (ТОЛЬКО ради графа)         3.20 с   16.2 %
    оболочки (build_from_elements)    2.32 с   11.8 %
    graph_view                        1.86 с    9.4 %
    кодек (упаковка)                  0.99 с    5.0 %

Разбивка ОТМЕНИЛА гипотезу, с которой в неё входили: второй проход по L0 —
16.2 %, а не «причина». Интерфейс к `decompile` снял бы шестую часть беды.

Через маршрут, `демо-v3`: холодный 18.05 с -> тёплый 0.011 с, то есть 1640x.
Законно это потому, что ТЕЛО сцены детерминировано: две постройки подряд дали
побайтно одинаковые 5 154 042 байта, разошлись ровно пять полей заголовка —
показания секундомера, которые обязаны отличаться.
"""

import os
import pathlib
import unittest

from kukai.viewer import cache as C


def _run_dir(name="sob62_fas_r23_v19"):
    from kukai.viewer.scene import run_root
    return run_root() / name


class TheKeyCoversEverythingThatChangesTheAnswer(unittest.TestCase):
    """ТРЕБОВАНИЕ ИЗ ЧУЖОГО ОЖОГА. У кэша клешей ключ трижды не покрывал
    того, что меняет ответ: поднятый потолок возвращал СТАРЫЙ отказ."""

    def test_the_inputs_are_a_list_not_a_silent_hash(self):
        """Хеш одинаково убедительно выглядит и с полным набором входов, и с
        половиной. Дыру видно только в списке."""
        inputs = C.key_inputs("проба", _run_dir())
        self.assertIsInstance(inputs, list)
        self.assertTrue(any(i.startswith("version=") for i in inputs))
        self.assertTrue(any(i.startswith("run=") for i in inputs))
        self.assertTrue(any(i.startswith("graph=") for i in inputs))

    def test_the_graph_flag_is_in_the_key_because_it_changes_content(self):
        """С графом элементы получают `materialized`/`declared`, без него —
        `unknown`. Кэш без флага отдал бы серое здание тому, кто включил граф."""
        previous = os.environ.get("KUKAI_IR_BUILDING_GRAPH")
        try:
            os.environ.pop("KUKAI_IR_BUILDING_GRAPH", None)
            off = C.key_for("проба", _run_dir())
            os.environ["KUKAI_IR_BUILDING_GRAPH"] = "1"
            self.assertNotEqual(C.key_for("проба", _run_dir()), off)
        finally:
            if previous is None:
                os.environ.pop("KUKAI_IR_BUILDING_GRAPH", None)
            else:
                os.environ["KUKAI_IR_BUILDING_GRAPH"] = previous

    def test_the_format_version_is_in_the_key(self):
        """Меняется кодек — обязаны протухнуть все записи, иначе клиент
        получит вчерашний формат сегодняшним разбором."""
        self.assertIn(f"version={C.CACHE_VERSION}",
                      C.key_inputs("проба", _run_dir()))

    def test_an_unreadable_directory_gives_no_key_at_all(self):
        """Ключа нет — кэш обязан промахнуться, а не выдать запись,
        обоснованную неизвестно чем."""
        self.assertIsNone(C.key_inputs("нет", pathlib.Path("/нет/такого")))
        self.assertEqual(C.key_for("нет", pathlib.Path("/нет/такого")), "")


class TheKeyCoversNothingThatDoesNot(unittest.TestCase):
    """ОПРОВЕРГАЮЩИЙ ТЕСТ СВОЕГО ЖЕ КЛЮЧА, И ОШИБКА БЫЛА ЗЕРКАЛЬНОЙ.

    У кэша клешей ключ НЕ ПОКРЫВАЛ того, что меняет ответ. Здесь он ПОКРЫВАЛ
    то, что ответ НЕ меняет: `.last_access` — отметку обращения, которую
    ставит `snapshot_io.touch_last_access` при каждом чтении файла разбора.

    Замер: открыть панель «план против объёма» (она зовёт `preview_snapshot`)
    — и ключ менялся 26243642fc0a722a9229 -> ebe15ccec14bdfd05399. Кэш
    переставал попадать НАВСЕГДА у любого, кто пользовался сверкой, и
    переставал МОЛЧА: он выглядел работающим, просто каждый раз строил заново.

    Ключ, покрывающий лишнее, ломает кэш; ключ, покрывающий недостаточно,
    ломает правильность. Обе ошибки про одно: набор входов обязан быть РОВНО
    множеством того, что меняет ответ.
    """

    def test_the_access_marker_is_not_an_input(self):
        inputs = C.key_inputs("проба", _run_dir())
        self.assertFalse([i for i in inputs if ".last_access" in i])

    def test_reading_the_run_does_not_change_the_key(self):
        from kukai.ir import preview as P
        before = C.key_for("проба", _run_dir())
        P.preview_snapshot(_run_dir())
        self.assertEqual(C.key_for("проба", _run_dir()), before)

    def test_the_marker_name_comes_from_its_owner(self):
        """Своя копия имени разъехалась бы при переименовании и вернула бы
        дефект молча."""
        import inspect
        self.assertIn("LAST_ACCESS_MARKER", inspect.getsource(C._not_inputs))


class AStaleEntryIsRefusedNotServed(unittest.TestCase):
    """Кэшированная сцена здания, которое пересобрали, — это здание, которого
    нет. Отказ и перестройка, а не тихая выдача старого."""

    def test_touching_an_input_invalidates_the_key(self):
        import time
        victim = _run_dir() / "tree.json"
        before = C.key_for("проба", _run_dir())
        original = victim.stat().st_mtime
        try:
            os.utime(victim, (time.time() + 5, time.time() + 5))
            self.assertNotEqual(C.key_for("проба", _run_dir()), before)
        finally:
            os.utime(victim, (original, original))
        self.assertEqual(C.key_for("проба", _run_dir()), before)

    def test_a_truncated_entry_is_a_miss_not_garbage(self):
        """Обрезанный файл, отдающий внутренне согласованный заголовок, —
        ровно тот дефект, который снапшот клеша ловит исключением."""
        C.purge()
        C.store("проба-порча", b"x" * 100, build_ms=1.0)
        blob_path, _ = C._paths("проба-порча")
        blob_path.write_bytes(b"short")
        self.assertIsNone(C.load("проба-порча"))
        C.purge()

    def test_a_missing_entry_is_a_miss(self):
        self.assertIsNone(C.load("такого-ключа-нет"))


class ItNamesItselfAndItsAge(unittest.TestCase):
    """Тайминги в заголовке принадлежат ИСХОДНОЙ постройке. Отдать их как свои
    значило бы сообщить «собрано за 20 с» про чтение, занявшее миллисекунду,
    — то есть соврать прибором."""

    def test_a_hit_carries_age_and_the_warning(self):
        C.purge()
        C.store("проба-возраст", b"blob", build_ms=1234.5,
                inputs=["version=x", "run=y"])
        loaded = C.load("проба-возраст")
        self.assertIsNotNone(loaded)
        _, note = loaded
        self.assertTrue(note["hit"])
        self.assertIn("age_s", note)
        self.assertEqual(note["build_ms"], 1234.5)
        self.assertIn("ИСХОДНОЙ", note["ru"])
        self.assertEqual(note["inputs"], ["version=x", "run=y"])
        C.purge()

    def test_the_switch_off_restores_the_old_behaviour(self):
        """Выключенный кэш = поведение до этой волны: каждый платит холодное
        открытие сам."""
        previous = os.environ.get("KUKAI_KIR_SCENE_CACHE")
        os.environ["KUKAI_KIR_SCENE_CACHE"] = "0"
        try:
            self.assertFalse(C.enabled())
            self.assertIsNone(C.load("любой"))
            self.assertFalse(C.store("любой", b"x", build_ms=1.0))
        finally:
            if previous is None:
                os.environ.pop("KUKAI_KIR_SCENE_CACHE", None)
            else:
                os.environ["KUKAI_KIR_SCENE_CACHE"] = previous


class TheSceneBodyIsDeterministic(unittest.TestCase):
    """Кэш законен ТОЛЬКО потому, что содержимое стабильно, и это проверено, а
    не предположено: две постройки дали побайтно одинаковое ТЕЛО, а разошлись
    ровно `timing_ms.*` и `graph.elapsed_ms` — показания секундомера."""

    def test_two_builds_agree_on_the_body(self):
        import json
        import struct
        from kukai.viewer.scene import scene_from_decompile

        def split(blob):
            head_len = struct.unpack_from("<I", blob, 8)[0]
            return (json.loads(blob[12:12 + head_len].decode("utf-8")),
                    blob[12 + head_len:])

        head_a, body_a = split(scene_from_decompile("sob62_fas_r23_v19")[0])
        head_b, body_b = split(scene_from_decompile("sob62_fas_r23_v19")[0])
        self.assertEqual(body_a, body_b, "тело сцены обязано быть стабильным")
        differing = {k for k in set(head_a) | set(head_b)
                     if head_a.get(k) != head_b.get(k)}
        self.assertTrue(differing <= {"timing_ms", "graph"},
                        f"разошлось не только время: {differing}")


class BoundedByBytesNotByEntries(unittest.TestCase):
    """Сцена фасада 0.5 МБ, сцена демо-v3 5.2 МБ. Считать их одинаково значит
    не считать; безлимитный кэш — утечка с хорошим названием."""

    def test_the_ceiling_is_in_bytes(self):
        self.assertGreaterEqual(C._max_bytes(), 10_000_000)

    def test_stats_name_every_outcome(self):
        stats = C.stats()
        for key in ("hit", "miss", "stored", "evicted", "errors", "entries",
                    "bytes", "max_bytes", "enabled", "version"):
            self.assertIn(key, stats)
