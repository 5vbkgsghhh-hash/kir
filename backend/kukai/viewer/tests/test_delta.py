"""ДОГОВОР ДЕЛЬТЫ: транспорт живой сессии и ответ «что изменилось».

ЗАМЕР, РАДИ КОТОРОГО ОНА НАПИСАНА (11.08.2026, трубы по 20 опов в программе):

| программ | элементов | ЦЕЛОЕ           | ДЕЛЬТА (+1 программа) |
|---------:|----------:|----------------:|----------------------:|
|       10 |       200 |  15 мс /  21 КБ |     2.0 мс / 9.9 КБ   |
|       50 |     1 000 |  69 мс /  71 КБ |     1.8 мс / 9.9 КБ   |
|      150 |     3 000 | 247 мс / 197 КБ |     1.8 мс / 10.0 КБ  |
|      300 |     6 000 | 479 мс / 387 КБ |     2.0 мс / 10.0 КБ  |

Главное в таблице — не 479 против 2.0, а то, что колонка дельты НЕ РАСТЁТ.
При опросе раз в 1.5 с полная пересборка съедала треть времени сессии и
росла линейно; трёхчасовая сессия на этом и заканчивалась.
"""

import json
import struct
import unittest

from kukai.live import journal as _journal
from kukai.viewer import live_scene as L

SNAPSHOT = {
    "levels": [{"id": 1, "name": "L1", "elevation_mm": 0.0}],
    "pipe_types": [{"id": 30, "name": "Сталь",
                    "section": {"kind": "nominal_table",
                                "source": "PipeSegment.GetSizes",
                                "sizes": [[100.0, 114.3]]}}],
}


def _pipe(oid, y=0.0):
    return {"op": "create_pipe", "id": oid,
            "p0_mm": [0.0, y, 2800.0], "p1_mm": [12000.0, y, 2800.0],
            "diameter_mm": 100.0,
            "pipe_type": {"by": "name", "value": "Сталь"},
            "level": {"by": "name", "value": "L1"}}


def _header(blob):
    head_len = struct.unpack_from("<I", blob, 8)[0]
    return json.loads(blob[12:12 + head_len].decode("utf-8"))


def _ids(blob):
    header = _header(blob)
    base = 12 + struct.unpack_from("<I", blob, 8)[0]
    span = next(b for b in header["buffers"] if b["name"] == "ids")
    raw = blob[base + span["offset"]:
               base + span["offset"] + span["length"]].decode("utf-8")
    return raw.split("\n") if raw else []


class DeltaBase(unittest.TestCase):

    DEVICE = "тест-дельта"
    DOC = "тест-док"

    def setUp(self):
        key = _journal.key_for(self.DEVICE, self.DOC)
        _journal.reset(key)
        _journal.remember_sections(key, SNAPSHOT)
        _journal.append(key, {"ops": [{"op": "create_level", "id": "lv",
                                       "name": "L1", "elev_mm": 0.0}]})
        for i in range(3):
            _journal.append(key, {"ops": [_pipe(f"p{j}", i * 100.0 + j)
                                          for j in range(2)]})
        self.key = key

    def _full(self):
        blob, meta = L.scene_from_session(self.DEVICE, self.DOC, 0)
        return blob, meta, _header(blob)


class AStaleBaseIsRefusedNotGuessed(DeltaBase):
    """Приклеить хвост к чужой базе значит показать здание, которого никогда
    не существовало. Пустой экран хотя бы виден."""

    def test_a_delta_without_a_base_is_refused(self):
        """Молчаливое согласие на неизвестную базу — та же склейка, только с
        ленью вместо ошибки."""
        _, _, header = self._full()
        with self.assertRaises(L.StaleBase):
            L.scene_from_session(self.DEVICE, self.DOC,
                                 header["journal"]["next_seq"], "")

    def test_a_delta_with_a_foreign_base_is_refused(self):
        _, _, header = self._full()
        with self.assertRaises(L.StaleBase):
            L.scene_from_session(self.DEVICE, self.DOC,
                                 header["journal"]["next_seq"], "0" * 32)

    def test_the_refusal_names_both_digests(self):
        """Отказ обязан называть причину: молчащий откат неотличим от поломки."""
        _, _, header = self._full()
        try:
            L.scene_from_session(self.DEVICE, self.DOC,
                                 header["journal"]["next_seq"], "0" * 32)
        except L.StaleBase as exc:
            self.assertIn(header["base_digest"], str(exc))
            self.assertIn("since=0", str(exc))
        else:
            self.fail("протухшая база принята")

    def test_a_matching_base_is_accepted(self):
        _, _, header = self._full()
        _journal.append(self.key, {"ops": [_pipe("new", 999.0)]})
        blob, meta = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        self.assertTrue(_header(blob)["delta"])
        self.assertEqual(meta["honesty"]["total"], 1)


class EverythingThatCanChangeThePastInvalidatesTheBase(DeltaBase):
    """Дельта законна ровно тогда, когда прошлое неизменно. Каналов, через
    которые новая программа меняет СТАРЫЙ элемент, ровно три, и подпись базы
    обязана покрывать все три."""

    def test_a_new_datum_invalidates_it(self):
        """`create_level` задаёт отметку, на которую по имени ссылаются
        программы, пришедшие РАНЬШЕ."""
        before = self._full()[2]["base_digest"]
        _journal.append(self.key, {"ops": [{"op": "create_level", "id": "lv2",
                                            "name": "L2", "elev_mm": 3300.0}]})
        self.assertNotEqual(self._full()[2]["base_digest"], before)

    def test_a_new_type_snapshot_invalidates_it(self):
        """Толщина стены и наружный диаметр трубы приходят из ТИПА: смена
        снимка пересчитывает тела ВСЕХ элементов."""
        before = self._full()[2]["base_digest"]
        _journal.remember_sections(self.key, {"levels": [
            {"id": 9, "name": "L9", "elevation_mm": 1.0}]})
        self.assertNotEqual(self._full()[2]["base_digest"], before)

    def test_eviction_invalidates_it(self):
        """Вытеснение убирает программы, которые у клиента уже нарисованы."""
        digest_a = L.base_digest([], None, 0)
        digest_b = L.base_digest([], None, 1)
        self.assertNotEqual(digest_a, digest_b)

    def test_appending_an_ordinary_program_does_not_invalidate_it(self):
        """Ссылки `ref` по `KIR-L003` не выходят за пределы своей программы,
        поэтому обычная программа прошлое не трогает. Если бы трогала, дельта
        была бы невозможна в принципе."""
        before = self._full()[2]["base_digest"]
        _journal.append(self.key, {"ops": [_pipe("ещё", 555.0)]})
        self.assertEqual(self._full()[2]["base_digest"], before)


class AddressesAndOriginSurviveTheSeam(DeltaBase):
    """Два способа склеить здание из двух систем отсчёта, и оба тихие."""

    def test_delta_addresses_equal_the_ones_the_whole_scene_would_give(self):
        """Дельта, начавшая нумерацию заново с `p1`, выдала бы новым элементам
        адреса, которые у клиента уже заняты старыми, и склейка молча
        ПОДМЕНИЛА бы их: тело нашлось бы, просто чужое."""
        _, _, header = self._full()
        cursor, digest = header["journal"]["next_seq"], header["base_digest"]
        _journal.append(self.key, {"ops": [_pipe("p0", 777.0),
                                           _pipe("p1", 778.0)]})
        delta, _ = L.scene_from_session(self.DEVICE, self.DOC, cursor, digest)
        whole, _ = L.scene_from_session(self.DEVICE, self.DOC, 0)
        fresh = set(_ids(delta))
        self.assertTrue(fresh)
        self.assertTrue(fresh <= set(_ids(whole)),
                        f"адреса дельты не встречаются в целом: {fresh}")

    def test_the_origin_is_pinned_and_identical(self):
        """Кодек пишет координаты СМЕЩЕНИЯМИ от начала. Начало, посчитанное по
        габариту среза, сдвинуло бы дельту на величину, которую никто не
        заметит, а расхождение росло бы плавно."""
        _, _, header = self._full()
        _journal.append(self.key, {"ops": [_pipe("далеко", 9_000_000.0)]})
        delta, _ = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        self.assertEqual(_header(delta)["origin_mm"], header["origin_mm"])

    def test_the_origin_depends_only_on_datums(self):
        """Начало живой сцены обязано зависеть ТОЛЬКО от того, чего дельта не
        меняет. Иначе оно поехало бы вместе с элементами."""
        self.assertEqual(L.live_origin([]), (0.0, 0.0, 0.0))
        self.assertEqual(
            L.live_origin([{"op": "create_level", "elev_mm": -8500.0},
                           {"op": "create_level", "elev_mm": 3300.0}]),
            (0.0, 0.0, -8500.0))

    def test_a_building_too_far_from_the_origin_is_named(self):
        """За `FLOAT32_EXACT_MM` миллиметр перестаёт быть представимым, и
        склейка поехала бы СУБМИЛЛИМЕТРОВО, то есть незаметно. Радиус
        проверяется, а не обещается."""
        self.assertEqual(L.FLOAT32_EXACT_MM, 16_777_216.0)
        _journal.append(self.key, {"ops": [
            _pipe("очень_далеко", 40_000_000.0)]})
        _, meta = L.scene_from_session(self.DEVICE, self.DOC, 0)
        self.assertTrue(meta["origin_overflow"])
        self.assertGreater(meta["origin_far_mm"], L.FLOAT32_EXACT_MM)

    def test_datums_ride_as_context_so_new_elements_land_on_their_level(self):
        """Без `create_level` у среза нет отметки этажа, и новые элементы
        легли бы на нулевую: дельта рисовала бы верно только первый этаж."""
        _, _, header = self._full()
        _journal.append(self.key, {"ops": [_pipe("свежая", 888.0)]})
        _, meta = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        self.assertGreaterEqual(meta["context_ops"], 1)


class PartialStaysUntilTheDeltaIsClosed(DeltaBase):
    """Условие лида: пока хвост возможен, он обязан называться хвостом.
    Красный баннер уходит вместе с последней возможностью его получить, а не
    раньше — а сегодня хвост возможен, потому что дельта и есть хвост."""

    def test_a_delta_is_still_marked_partial(self):
        _, _, header = self._full()
        _journal.append(self.key, {"ops": [_pipe("ещё", 111.0)]})
        blob, _ = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        fresh = _header(blob)
        self.assertTrue(fresh["partial"])
        self.assertTrue(fresh["delta"])
        self.assertIn("ХВОСТ", fresh["partial_ru"])

    def test_a_whole_scene_is_neither_partial_nor_a_delta(self):
        header = self._full()[2]
        self.assertFalse(header["partial"])
        self.assertFalse(header["delta"])
        self.assertTrue(header["base_digest"])


class TheClientSideMergeIsCheckedByNode(unittest.TestCase):
    """Склейка живёт у клиента и питоном не проверяется — но проверяется.

    `verify_merge.mjs` рядом с этим файлом сверяет склейку с целой сценой
    ПОЭЛЕМЕНТНО: геометрию через слот (ровно так, как её возьмёт
    рисовальщик), обе оси честности, оси графа и таблицы строк. Ошибка в
    сдвиге слотов ничего не роняет — она показывает элементу ЧУЖОЕ тело, и
    здание остаётся правдоподобным; такую ошибку ловит только равенство.

    Здесь держится ровно то, что можно держать питоном: инструмент существует
    и лежит в дереве, а не в /tmp одного прогона.
    """

    def test_the_checker_ships_with_the_tests(self):
        import pathlib
        tool = pathlib.Path(__file__).with_name("verify_merge.mjs")
        self.assertTrue(tool.exists())
        text = tool.read_text(encoding="utf-8")
        self.assertIn("mergeScenes", text)
        self.assertIn("ВЫДУМАЛА", text)

    def test_the_merge_module_has_no_dom_or_three_dependency(self):
        """`scene-data.js` вынесен из `viewer.js` именно затем, чтобы его
        можно было прогнать в node. Импорт three.js вернул бы его обратно в
        непроверяемое.

        🔴 ПРИБОР ПОЧИНЕН 14.08.2026, ДВА ДЕФЕКТА СРАЗУ — и оба наши любимые.

        ПЕРВЫЙ: `assertNotIn("three", text)` искал СЛОВО, а не зависимость.
        Собственная шапка модуля говорит «без DOM и без three.js» — и тест
        краснел на своём же комментарии, ничего не сообщая о зависимостях.
        Ярлык вместо ветки: прибор врал в обе стороны, потому что
        `// three.js не нужен` красит его так же, как настоящий импорт.

        ВТОРОЙ: он читал ПРОД (`/opt/kukai-rebuild1/...`), а не дерево, в
        котором лежит сам. На чужой машине он молча пропускался, а здесь
        проверял файл, которого в ветке может не быть вовсе — то есть
        сообщал о СОСЕДНЕЙ копии. Свой файл ищется от `__file__`; прод
        остаётся запасным путём и НАЗЫВАЕТСЯ, когда используется.
        """
        import pathlib
        import re
        here = pathlib.Path(__file__).resolve()
        # kukai/viewer/tests -> kukai/viewer -> kukai -> backend -> корень
        own = here.parents[4] / "assets" / "viewer" / "scene-data.js"
        prod = pathlib.Path("/opt/kukai-rebuild1/assets/viewer/scene-data.js")
        path = own if own.exists() else prod
        if not path.exists():
            self.skipTest(f"нет ни {own}, ни {prod}")
        text = path.read_text(encoding="utf-8")
        # Комментарии вырезаются: зависимость живёт в КОДЕ, и судить о ней
        # надо по коду. Строковые литералы остаются — `import("three")` тоже
        # зависимость.
        code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        code = re.sub(r"(?m)//.*$", "", code)
        for bad in ("three", "document", "window", "requestAnimationFrame"):
            self.assertNotIn(bad, code,
                             f"{path} тянет {bad!r} — модуль перестал быть "
                             "проверяемым в node")
        # КОНТРОЛЬ-PASS: вырезание не съело весь файл, иначе проверка была бы
        # зелёной по построению.
        self.assertIn("mergeScenes", code)


class TheCompletenessFlagSurvivesTheMerge(DeltaBase):
    """🔴 «ХВОСТ» — СВОЙСТВО НАКОПЛЕННОГО, А НЕ ПОСЛЕДНЕГО ОТВЕТА.

    НАЙДЕНО 16.08.2026 НА ЖИВОМ ХОДЕ ВЛАДЕЛЬЦА, и цена была — весь продукт.
    Он попросил коробку 4×4, увидел её в окне КИР, нажал «Отправить в Revit» и
    получил: «на экране ХВОСТ журнала, а не здание: часть программ в эту сцену
    не попала». Дословная его реакция: «я как человек вообще понять не могу
    почему и что не так».

    Обе половины были по отдельности правы. Сервер ставит `partial = since > 0`
    (`live_scene.py:243`) и говорит правду О СВОИХ БАЙТАХ. Кнопка читает
    `data.header.partial` и спрашивает про СЦЕНУ. Между ними стоял
    `mergeScenes`, бравший заголовок целиком от дельты, — и правда об ответе
    становилась ложью о сцене. Именной дефект этого проекта дословно: величина
    УТВЕРЖДАЕТСЯ в одном месте, ЧИТАЕТСЯ в другом, и совпасть их не заставляет
    ничто.

    ЦЕНА — ПО ПОСТРОЕНИЮ, А НЕ ПО НЕВЕЗЕНИЮ. Живая сессия начинает кадром
    `since=0`, дальше идут дельты; ПЕРВАЯ ЖЕ дельта — даже пустая, даже
    «ничего нового» — ставила признак навсегда. Перенос в Revit был мёртв у
    всякого, кто держит окно открытым дольше одного опроса.

    ПОЧЕМУ ПРОВЕРЯЕТСЯ NODE, А НЕ ПИТОНОМ. Склейка живёт у клиента, и питон её
    не исполняет. Прибор рядом (`verify_merge.mjs`) сверяет ГЕОМЕТРИЮ склейки и
    к этому вопросу не относится; здесь ровно одна величина — честность о
    полноте. Блобы кладёт этот тест: инструмент, чьи входы никто не готовит,
    не запускается никогда — `verify_merge.mjs` ровно в таком состоянии и
    живёт, его питоновский спутник обещан докстрокой и в дереве отсутствует.
    """

    def _blobs(self, into):
        """База (`since=0`) и хвост (`since>0`) — ПРОД-КОДОМ, не руками.

        Форма 27: тест, строящий вход своими руками, зелен на форме, которой
        прод не производит.
        """
        base, _, header = self._full()
        _journal.append(self.key, {"ops": [_pipe("хвост", 777.0)]})
        delta, _ = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        (into / "d_base.bin").write_bytes(base)
        (into / "d_delta.bin").write_bytes(delta)

    def _run_node(self, module_path):
        import pathlib
        import subprocess
        import tempfile
        tool = pathlib.Path(__file__).with_name("verify_partial.mjs")
        self.assertTrue(tool.exists(), "прибор не приехал вместе с тестом")
        with tempfile.TemporaryDirectory() as tmp:
            into = pathlib.Path(tmp)
            self._blobs(into)
            return subprocess.run(
                ["node", str(tool), str(into), str(module_path)],
                capture_output=True, text=True, timeout=120)

    def _module(self):
        import pathlib
        import shutil
        if shutil.which("node") is None:
            self.skipTest("node не установлен — прибор не запускался")
        own = pathlib.Path(__file__).resolve().parents[4] / \
            "assets" / "viewer" / "scene-data.js"
        if not own.exists():
            self.skipTest(f"нет {own}")
        return own

    def test_a_whole_scene_plus_a_tail_is_still_whole(self):
        proc = self._run_node(self._module())
        self.assertEqual(proc.returncode, 0,
                         f"\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("склейка целого с хвостом — не хвост", proc.stdout)

    def test_the_instrument_reddens_on_the_broken_merge(self):
        """КОНТРОЛЬ-FAIL, И ОН ПОВЕДЕНЧЕСКИЙ, А НЕ «СИМВОЛА НЕТ».

        Берётся НАСТОЯЩИЙ модуль, и в нём восстанавливается ровно прежнее
        поведение — заголовок целиком от дельты. Зелёный прибор, не умеющий
        покраснеть, — не прибор; на этом дереве таких нашли шесть за вечер.
        """
        import pathlib
        import re
        import tempfile
        module = self._module()
        text = module.read_text(encoding="utf-8")
        broken = re.sub(
            r"\n\s*partial: partial,\n\s*partial_ru: \(partial.*?\),\n",
            "\n", text, flags=re.S)
        self.assertNotEqual(broken, text, "мутация не нашла своё место")
        with tempfile.TemporaryDirectory() as tmp:
            hurt = pathlib.Path(tmp) / "scene-data.js"
            hurt.write_text(broken, encoding="utf-8")
            proc = self._run_node(hurt)
        self.assertEqual(proc.returncode, 1,
                         f"прибор не покраснел на сломанной склейке:"
                         f"\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("Кнопка переноса мертва по построению", proc.stdout)
