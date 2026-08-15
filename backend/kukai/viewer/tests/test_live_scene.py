"""Живая сцена: то, что ЗАЯВЛЕНО, но в Revit ещё не ушло.

Тесты держат факты, каждый из которых найден замером 11.08.2026, а не выведен
рассуждением. Два из них — опровергающие тесты на дефекты, найденные уже
после того, как код «работал».
"""

import json
import struct
import unittest

from kukai.viewer import honesty as H
from kukai.viewer import live_scene as L

#: Снимок типов ОТКРЫТОЙ модели в той форме, в какой его кладёт стадия ground
#: (`kukai/ir/tests/test_type_sections.py`). Форма взята оттуда, а не выдумана:
#: своя форма проверяла бы наш разбор нашего же вымысла.
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


def _live_meta():
    return L.scene_from_programs([{"ops": [_pipe("p0")]}], snapshot=None)[1]


class QualificationIsDoneExactlyOnce(unittest.TestCase):
    """ОПРОВЕРГАЮЩИЙ ТЕСТ ДЕФЕКТА 11.08.

    `bundle_elements` квалифицирует адреса САМ (`bundle_oid` -> `p1/w0`), а
    `preview` — не квалифицирует вовсе. Пока пачка подавалась обоим уже
    квалифицированной, тела приезжали под `p1/p1/w0`, с контурами не
    сходились, и КАЖДЫЙ элемент с телом рисовался ДВАЖДЫ: телом и призраком.
    Замер: перепись показывала 13 элементов там, где их 8.
    """

    def test_an_element_with_a_body_is_not_also_drawn_as_a_ghost(self):
        pack = [{"ops": [_pipe("p0"), _pipe("p1", 1000.0)]}]
        blob, meta = L.scene_from_programs(pack, snapshot=SNAPSHOT)
        header = _header(blob)
        self.assertEqual(header["elements"], meta["honesty"]["total"])
        self.assertEqual(meta["bodies"], 2)
        self.assertEqual(header["elements"], 2)
        self.assertEqual(meta["honesty"]["by_fidelity"].get("no_body", 0), 0)

    def test_the_same_op_id_in_two_programs_gets_two_addresses(self):
        """`id` уникален ВНУТРИ программы; между программами совпадение
        законно. Без квалификации две трубы схлопнулись бы в одну."""
        pack = [{"ops": [_pipe("p0")]}, {"ops": [_pipe("p0")]}]
        blob, meta = L.scene_from_programs(pack, snapshot=SNAPSHOT)
        self.assertEqual(_header(blob)["elements"], 2)
        self.assertEqual(meta["id_collisions"], 0)

    def test_refs_survive_qualification(self):
        """`ref` по `KIR-L003` указывает только внутрь своей программы, поэтому
        одинаковый префикс у цели и у ссылки сохраняет связь. Если бы не
        сохранял, дверь потеряла бы хозяина и уехала бы в перепись."""
        pack = [[{"op": "create_level", "id": "lv", "name": "L1",
                  "elev_mm": 0.0},
                 {"op": "create_wall", "id": "w0", "p0_mm": [0.0, 0.0],
                  "p1_mm": [12000.0, 0.0], "height_mm": 3200.0,
                  "level": {"by": "ref", "value": "lv"}}]]
        wall = L._qualify(pack)[0][1]
        self.assertEqual(wall["id"], "p1/w0")
        self.assertEqual(wall["level"], {"by": "ref", "value": "p1/lv"})


class BodiesNeedTheLiveModel(unittest.TestCase):
    """ЗАМЕР, ЗАДАЮЩИЙ ВЕСЬ ЭКРАН: без снимка открытой модели тел нет.

    Толщина стены и наружный диаметр трубы живут в ТИПЕ. Замер 11.08: пачка
    из шести стен и трубы даёт 0 тел из 7, все семь — `needs_live_model`.
    Лид перемерил то же на масштабе: `snowdon_plumb_v4` — 905 тел без снимка
    против 16 247 из 16 257 (99.94 %) со снимком. Значит покрытие телами
    решает НЕ проводка, а наличие снимка, и экран обязан это говорить.
    """

    def test_without_a_snapshot_there_are_no_bodies_at_all(self):
        pack = [{"ops": [_pipe("p0"), _pipe("p1", 1000.0)]}]
        _, meta = L.scene_from_programs(pack, snapshot=None)
        self.assertEqual(meta["bodies"], 0)
        self.assertGreater(meta["bodies_declared"], 0)
        self.assertIn("needs_live_model", meta["blind_by_class"])

    def test_with_a_snapshot_the_same_pack_gets_bodies(self):
        pack = [{"ops": [_pipe("p0"), _pipe("p1", 1000.0)]}]
        _, meta = L.scene_from_programs(pack, snapshot=SNAPSHOT)
        self.assertEqual(meta["bodies"], 2)
        self.assertNotIn("needs_live_model", meta["blind_by_class"])

    def test_the_absence_of_a_snapshot_is_stated_in_words(self):
        """Молчание тут читалось бы как «здание такое». Оно не такое — просто
        мы не открывали модель.

        14.08.2026: тест держался за СЛОВО «НЕТ» в прозе, а не за факт. Когда
        двоичное `sections` развели на три состояния, проза стала точнее
        («снимок НЕ ЗАПРАШИВАЛСЯ» вместо «снимка НЕТ») — и тест покраснел на
        УЛУЧШЕНИИ. Пин по подстроке прозы — не прибор: он краснеет от правки
        текста и молчит о подмене смысла. Держимся за состояние.
        """
        _, meta = L.scene_from_programs([{"ops": [_pipe("p0")]}], snapshot=None)
        self.assertFalse(meta["sections_present"])
        self.assertEqual(meta["sections_state"], "absent")
        self.assertTrue(meta["sections_ru"].strip())

    def test_no_snapshot_and_an_empty_snapshot_are_different_facts(self):
        """ОПРОВЕРГАЮЩИЙ ТЕСТ К ТРЁМ СОСТОЯНИЯМ.

        `bool(sections)` сводил «заземление не дошло» и «спросили, сечений в
        документе нет» к одному ответу. Это разные факты: первый — про наш
        путь, второй — про документ, и чинят их разные люди. Контроль-FAIL:
        вернуть `bool()` — оба вызова дадут одно и то же, и тест покраснеет.
        """
        _, absent = L.scene_from_programs([{"ops": [_pipe("p0")]}],
                                          snapshot=None)
        _, empty = L.scene_from_programs([{"ops": [_pipe("p0")]}], snapshot={})
        self.assertEqual(absent["sections_state"], "absent")
        self.assertEqual(empty["sections_state"], "empty")
        self.assertNotEqual(absent["sections_ru"], empty["sections_ru"])
        # И ОБА ГОВОРЯТ ОДНО И ТО ЖЕ ПРО ТЕЛА: их не будет. Разное объяснение
        # не должно превращаться в разное обещание.
        self.assertFalse(absent["sections_present"])
        self.assertFalse(empty["sections_present"])

    def test_a_bodiless_element_is_a_ghost_and_not_a_disappearance(self):
        """Пропавший элемент неотличим от несуществующего. Поэтому он
        рисуется контуром плана и помечается `no_body`."""
        _, meta = L.scene_from_programs([{"ops": [_pipe("p0")]}], snapshot=None)
        self.assertEqual(meta["honesty"]["by_fidelity"].get("no_body"), 1)
        self.assertTrue(meta["honesty"]["balanced"])


class ADeclaredWallReachesTheScreenWithABody(unittest.TestCase):
    """СИМПТОМ ВЛАДЕЛЬЦА 14.08, ЦЕЛИКОМ И НА ЕГО УРОВНЕ.

    Он написал «построй стену» в окне КИР, путь прошёл насквозь — и сцена
    осталась пустой. Причина жила через два модуля отсюда: стене не разрешали
    строить тело по объявленной полосе, а габарита у объявленной стены нет
    ПО ПОСТРОЕНИЮ, так что выбор был «полоса против ничего».

    Тесты в `clash/tests/test_prism_source.py` держат эту правку у самой
    оболочки. Этот держит её ТАМ, КУДА СМОТРИТ ВЛАДЕЛЕЦ: радиус правки — граф
    импортов, а не каталог, и половина сегодняшних промахов была ровно в том,
    что проверялась функция, а не путь.
    """

    WALL_SNAPSHOT = {
        "levels": [{"id": 1, "name": "L1", "elevation_mm": 0.0}],
        "wall_types": [{"id": 40, "name": "Типовой - 200мм",
                        "section": {"kind": "plate", "thickness_mm": 200.0,
                                    "uniform": True, "blockers": [],
                                    "source": "type"}}],
    }

    def _wall(self, named=True):
        op = {"op": "create_wall", "id": "w0",
              "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [6000.0, 0.0, 0.0],
              "height_mm": 3000.0,
              "level": {"by": "name", "value": "L1"}}
        if named:
            op["type"] = {"by": "name", "value": "Типовой - 200мм"}
        return op

    def test_the_wall_has_a_body_on_the_screen(self):
        _, meta = L.scene_from_programs([{"ops": [self._wall()]}],
                                        snapshot=self.WALL_SNAPSHOT)
        self.assertEqual(meta["bodies"], 1)
        self.assertEqual(meta["blind_by_class"], {})

    def test_a_wall_without_a_named_type_still_says_why(self):
        """КОНТРОЛЬ-FAIL: экран обязан уметь сказать «нет тела и вот почему».

        Без него предыдущий тест не отличал бы «тело построилось» от «причины
        замолчали». Это ровно ПЕРВЫЙ случай владельца — тип не назван, — и он
        обязан остаться названным.
        """
        _, meta = L.scene_from_programs([{"ops": [self._wall(named=False)]}],
                                        snapshot=self.WALL_SNAPSHOT)
        self.assertEqual(meta["bodies"], 0)
        self.assertIn("not_declared_by_program", meta["blind_by_class"])


class WhyThereIsNoBodyIsNamed(unittest.TestCase):

    def test_classes_come_from_the_owner_of_the_table(self):
        """Класс считает `clash_bundle`, а не копия здесь: шесть строк своей
        реализации разошлись бы с оригиналом молча."""
        from kukai.ir import clash_bundle as CB
        _, meta = L.scene_from_programs([{"ops": [_pipe("p0")]}], snapshot=None)
        self.assertTrue(set(meta["blind_by_class"]) <=
                        set(CB.BLIND_CLASS_RU) | {"unclassified"})
        self.assertEqual(meta["blind_class_ru"], dict(CB.BLIND_CLASS_RU))

    def test_each_class_ships_with_the_sentence_that_says_who_fixes_it(self):
        """«Нет тела» без причины бесполезно; с причиной это указание, что
        делать, и адресат у каждого класса разный: операнд правит АВТОР,
        снимок — стадия ground, замок содержания — `kukai/clash`."""
        for name, text in _live_meta()["blind_class_ru"].items():
            self.assertTrue(text.strip(), name)

    def test_a_hole_in_the_foreign_table_is_shown_not_swallowed(self):
        """Причина без класса уезжает в `unclassified` и печатается: иначе
        дыра в таблице читалась бы как отсутствие проблемы."""
        self.assertIn("blind_unclassified", _live_meta())

    def test_the_scope_of_the_class_is_admitted(self):
        """`BundleGeometry` считает причины ПАЧКОЙ. Приписать элементу класс
        было бы догадкой, надетой на элемент, а догадка на элементе читается
        как измерение."""
        self.assertIn("ПАЧКОЙ", _live_meta()["blind_scope_ru"])


class JournalFactsReachTheScreen(unittest.TestCase):
    """ОПРОВЕРГАЮЩИЙ ТЕСТ ВТОРОГО ДЕФЕКТА 11.08.

    Справка журнала дописывалась в `meta` ПОСЛЕ `builder.finish(meta)`.
    Заголовок лежит ВНУТРИ байтов сцены, поэтому вытеснение программ и
    отсутствие снимка доезжали до сервера и никогда — до экрана.
    Предупреждение существовало и молчало.
    """

    def test_the_journal_note_is_inside_the_encoded_header(self):
        blob, _ = L.scene_from_programs(
            [{"ops": [_pipe("p0")]}], snapshot=SNAPSHOT,
            journal={"evicted": 7, "truncated_ru": "семь вытеснено"})
        header = _header(blob)
        self.assertIsNotNone(header.get("journal"))
        self.assertEqual(header["journal"]["evicted"], 7)

    def test_no_journal_is_null_rather_than_a_missing_key(self):
        self.assertIsNone(
            _header(L.scene_from_programs([{"ops": [_pipe("p0")]}])[0])["journal"])


class HeightIsNeverInvented(unittest.TestCase):

    def test_a_missing_height_gets_a_conspicuous_stub_and_a_name(self):
        """Правдоподобное число хуже отсутствующего: 2500 мм спряталось бы
        среди настоящих стен, 100 мм видно сразу."""
        self.assertEqual(L.FALLBACK_HEIGHT_MM, 100.0)
        pack = [[{"op": "create_level", "id": "lv", "name": "L1",
                  "elev_mm": 0.0},
                 {"op": "create_wall", "id": "w0", "p0_mm": [0.0, 0.0],
                  "p1_mm": [12000.0, 0.0],
                  "level": {"by": "ref", "value": "lv"}}]]
        _, meta = L.scene_from_programs(pack)
        self.assertGreaterEqual(meta["height_unknown"], 1)
        self.assertIn("НЕ их высота", meta["height_unknown_ru"])


class AxesRideOnEveryElement(unittest.TestCase):

    def test_the_tally_matches_the_buffer_byte_for_byte(self):
        """Сводка, разошедшаяся с буфером, — подпись под непрочитанным."""
        blob, meta = L.scene_from_programs(
            [{"ops": [_pipe("p0"), _pipe("p1", 1000.0)]}], snapshot=SNAPSHOT)
        header = _header(blob)
        span = next(b for b in header["buffers"] if b["name"] == "elem_axes")
        base = 12 + struct.unpack_from("<I", blob, 8)[0]
        raw = struct.unpack_from(f"<{span['length']}B", blob,
                                 base + span["offset"])
        tally = {}
        for byte in raw:
            tally[str(byte)] = tally.get(str(byte), 0) + 1
        self.assertEqual(tally, meta["axes_tally"])

    def test_an_element_without_an_op_is_unjudgeable_not_clean(self):
        self.assertEqual(H.axes_byte(None), H.AXES_UNJUDGEABLE)
        self.assertNotEqual(H.AXES_UNJUDGEABLE, 0)


class UnprovenOpsAreDistinguishable(unittest.TestCase):

    def test_an_element_built_by_an_unproven_op_is_marked(self):
        """`tool_doc.UNPROVEN` — 30 записей на 11.08.2026. Элемент,
        построенный неподтверждённым опом, обязан быть отличим: «ворота его
        собирают» и «живьём его строили» — разные утверждения."""
        from kukai.ir.tool_doc import UNPROVEN
        self.assertIn("create_conduit", UNPROVEN)
        pack = [{"ops": [{"op": "create_conduit", "id": "c0",
                          "p0_mm": [0.0, 0.0, 2800.0],
                          "p1_mm": [12000.0, 0.0, 2800.0],
                          "diameter_mm": 50.0,
                          "level": {"by": "name", "value": "L1"}}]}]
        _, meta = L.scene_from_programs(pack, snapshot=SNAPSHOT)
        self.assertEqual(meta["honesty"]["by_trust"].get("op_unproven"), 1)


class ACursorSliceIsATailNotABuilding(unittest.TestCase):
    """ТРЕТИЙ ДЕФЕКТ 11.08, И ОН ТОЖЕ МОЙ.

    `/api/viewer/live?since=N` возвращал сцену, собранную ТОЛЬКО из программ
    после курсора, и по форме она ничем не отличалась от целого здания:
    заголовок нёс `elements`, перепись сходилась, картинка рисовалась. Замер
    на журнале из двух программ: `since=1` давал здание из ОДНОГО элемента,
    `since=2` — ПУСТОЕ здание, и оба выглядели исправными.

    Дельты сцены нет: `scene_from_programs` умеет строить только целое.
    Поэтому хвост обязан НАЗЫВАТЬСЯ хвостом — в корне заголовка, а не только
    в справке журнала.
    """

    def _session(self):
        from kukai.live import journal as journal_mod
        key = journal_mod.key_for("тест-устройство", "тест-док")
        journal_mod.reset(key)
        journal_mod.append(key, {"ops": [
            {"op": "create_level", "id": "lv", "name": "L1", "elev_mm": 0.0}]})
        journal_mod.append(key, {"ops": [_pipe("p0")]})
        return "тест-устройство", "тест-док"

    def _base(self, device, doc):
        """Подпись базы, которую клиент обязан вернуть вместе с курсором.

        14.08.2026: три теста ниже звали `scene_from_session(..., since>0)`
        БЕЗ неё и падали на `StaleBase`. Отказ верный — он появился позже
        тестов и защищает от приклеивания хвоста к чужой базе; устарели
        тесты. Подпись спрашивается у того же журнала, а не выдумывается
        здесь: второй источник разошёлся бы с первым молча.
        """
        from kukai.live import journal as journal_mod
        session = journal_mod.get(journal_mod.key_for(device, doc))
        return L.base_digest(list(getattr(session, "datums", ()) or ()),
                             getattr(session, "sections", None),
                             getattr(session, "programs_evicted", 0))

    def test_a_tail_without_the_base_signature_is_refused_by_name(self):
        """КОНТРОЛЬ-FAIL к трём тестам ниже: без подписи базы дельта обязана
        ОТКАЗАТЬ, а не собраться. Иначе хвост приклеится к чужому зданию, и
        оба будут выглядеть исправными."""
        device, doc = self._session()
        with self.assertRaises(L.StaleBase):
            L.scene_from_session(device, doc, 1)

    def test_since_zero_is_not_partial(self):
        device, doc = self._session()
        blob, _ = L.scene_from_session(device, doc, 0)
        self.assertFalse(_header(blob)["partial"])

    def test_a_positive_cursor_is_marked_partial_in_the_root_header(self):
        device, doc = self._session()
        blob, _ = L.scene_from_session(device, doc, 1, self._base(device, doc))
        header = _header(blob)
        self.assertTrue(header["partial"])
        self.assertIn("ХВОСТ", header["partial_ru"])

    def test_an_empty_tail_is_still_marked_rather_than_looking_like_a_void(self):
        """`since` за пределом журнала даёт НОЛЬ элементов. Пустое здание и
        здание, которого не показали, обязаны читаться по-разному."""
        device, doc = self._session()
        blob, meta = L.scene_from_session(device, doc, 99, self._base(device, doc))
        self.assertEqual(meta["honesty"]["total"], 0)
        self.assertTrue(_header(blob)["partial"])

    def test_the_note_says_how_many_of_how_many(self):
        device, doc = self._session()
        _, meta = L.scene_from_session(device, doc, 1, self._base(device, doc))
        self.assertEqual(meta["journal"]["since"], 1)
        self.assertEqual(meta["journal"]["returned"], 1)
        self.assertEqual(meta["journal"]["held"], 2)
