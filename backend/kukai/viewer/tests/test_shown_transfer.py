"""КНОПКА «ОТПРАВИТЬ В REVIT» НА СЦЕНЕ-СКЛЕЙКЕ.

Единственное место, где виртуальное становится настоящим, и она подписывает
ТО, ЧТО ЧЕЛОВЕК ВИДЕЛ. Пока сцена приезжала целиком, «показанное» и
«переносимое» совпадали по построению. Со склейкой из базы и хвостов это два
РАЗНЫХ вычисления, и любое их расхождение есть здание, которого инженер не
видел, построенное с его согласия.

ЗАМЕР ЦЕНЫ (11.08.2026, 300 программ / 6 000 элементов):

  * дельта БЕЗ подписи      1.9 мс
  * дельта С подписью       2.0 мс   (сложение 20 записей — 0.03 мс)
  * пересчёт подписи заново 8.5 мс   — столько стоил бы кадр, считай мы её
                                       не накоплением, а по всей сцене
  * панель, один раз по кнопке: сборка записей 50 мс, подпись 157 мс

То есть транспорт кнопкой не сломан: подпись едет накоплением и остаётся
O(нового) на кадр, а её полная стоимость платится один раз при нажатии.
"""

import os
import unittest

from kukai.live import journal as _journal
from kukai.live import showroom as _showroom
from kukai.live import transfer as _transfer
from kukai.viewer import live_scene as L


def _wall(oid, y):
    return {"op": "create_wall", "id": oid, "p0_mm": [0.0, y],
            "p1_mm": [9000.0, y], "height_mm": 3200.0,
            "level": {"by": "name", "value": "L1"}}


class ButtonBase(unittest.TestCase):

    DEVICE = "тест-кнопка"
    DOC = "тест-док"

    def setUp(self):
        os.environ.setdefault("KUKAI_KIR_TRANSFER", "1")
        self.key = _journal.key_for(self.DEVICE, self.DOC)
        _journal.reset(self.key)
        _showroom.forget(self.key)
        _journal.append(self.key, {"ops": [{"op": "create_level", "id": "lv",
                                            "name": "L1", "elev_mm": 0.0}]})
        _journal.append(self.key, {"ops": [_wall("w0", 0.0)]})

    def _shown(self):
        import json
        import struct
        blob, _ = L.scene_from_session(self.DEVICE, self.DOC, 0)
        head_len = struct.unpack_from("<I", blob, 8)[0]
        return json.loads(blob[12:12 + head_len].decode("utf-8"))


class TheSignatureIsOfWhatWasShown(ButtonBase):

    def test_a_matching_signature_is_ready_and_equal_to_the_transfer_one(self):
        """Равенство `requested` и `transfer` И ЕСТЬ «что видел, то и
        построится», выраженное равенством, а не обещанием."""
        header = self._shown()
        decision = _transfer.authorize_scene(
            self.key, shown_digest=header["shown_digest"])
        self.assertIs(decision.status, _transfer.Status.READY)
        self.assertEqual(decision.transfer_digest, decision.requested_digest)
        self.assertEqual(decision.programs, 2)

    def test_the_scene_publishes_the_signature_it_accumulated(self):
        self.assertTrue(self._shown()["shown_digest"])
        self.assertEqual(self._shown()["shown_digest"],
                         _showroom.scene_digest(self.key))


class ADivergenceRefusesBothVersions(ButtonBase):
    """Расхождение — отказ, а не выбор победителя: серверная версия не была на
    экране, панельную мы не считали."""

    def test_a_foreign_signature_is_refused(self):
        """ЧУЖАЯ ПОДПИСЬ ПРОТИВ ПОКАЗАННОГО — именно `shown_mismatch`.

        14.08.2026: тест был зелёным ПО УТЕЧКЕ. Он не показывал сцену вовсе,
        а `_showroom.forget()` чистил только кадры (`_ROOMS`) и не трогал
        накопленную подпись (`_SCENES`) — сюда доезжала подпись СОСЕДНЕГО
        теста, и «расхождение» получалось из чужого состояния. В одиночку
        тест падал, в пачке проходил; это не тест, а показание порядка
        запуска. Теперь сцена показывается явно, и утечки больше нет —
        `forget` чистит оба хранилища.
        """
        self._shown()
        decision = _transfer.authorize_scene(self.key, shown_digest="0" * 64)
        self.assertIs(decision.refusal, _transfer.Refusal.SHOWN_MISMATCH)

    def test_without_anything_shown_a_foreign_signature_is_not_a_mismatch(self):
        """КОНТРОЛЬ-ПАРА К ТЕСТУ ВЫШЕ, И ОНА ЖЕ — ОПРОВЕРЖЕНИЕ УТЕЧКИ.

        Та же чужая подпись, но сцену никто не показывал: сверять не с чем, и
        отказ обязан быть ДРУГИМ. Если `forget` снова перестанет чистить
        `_SCENES`, здесь появится `shown_mismatch` — и тест покраснеет.
        """
        decision = _transfer.authorize_scene(self.key, shown_digest="0" * 64)
        self.assertIs(decision.refusal, _transfer.Refusal.NOTHING_SHOWN)

    def test_the_refusal_names_both_signatures(self):
        """Отказ, не говорящий, что с чем не сошлось, неотличим от поломки."""
        header = self._shown()
        decision = _transfer.authorize_scene(self.key, shown_digest="0" * 64)
        joined = " ".join(decision.diverged)
        self.assertIn("0" * 64, joined)
        self.assertIn(header["shown_digest"], joined)
        self.assertEqual(decision.current_digest, header["shown_digest"])

    def test_an_empty_signature_is_a_mismatch_not_a_pass(self):
        """Панель, не приславшая подписи, не подписала ничего. Пропустить её
        значило бы согласиться на неизвестное."""
        self._shown()
        decision = _transfer.authorize_scene(self.key, shown_digest="")
        self.assertIs(decision.refusal, _transfer.Refusal.SHOWN_MISMATCH)

    def test_nothing_shown_is_its_own_refusal(self):
        """«Не совпало» и «не показывали» лечатся разным."""
        _showroom.forget(self.key)
        decision = _transfer.authorize_scene(self.key, shown_digest="что-то")
        self.assertIs(decision.refusal, _transfer.Refusal.NOTHING_SHOWN)

    def test_no_refusal_silently_picks_a_side(self):
        """Ни один отказ не имеет права вернуть `READY` с чужой подписью."""
        for digest in ("", "0" * 64, "короткая"):
            decision = _transfer.authorize_scene(self.key,
                                                 shown_digest=digest)
            self.assertIsNot(decision.status, _transfer.Status.READY)


class ATailCannotBeSentAsABuilding(ButtonBase):

    def test_partial_is_refused_even_with_a_matching_signature(self):
        """Подпись хвоста сойдётся сама с собой и ничего этим не докажет.
        Поэтому хвост проверяется ПЕРВЫМ."""
        header = self._shown()
        decision = _transfer.authorize_scene(
            self.key, shown_digest=header["shown_digest"], partial=True)
        self.assertIs(decision.refusal, _transfer.Refusal.PARTIAL_SCENE)

    def test_a_delta_scene_is_marked_partial_so_the_button_sees_it(self):
        """`partial` обязан доезжать до кнопки, а не оставаться на картинке."""
        header = self._shown()
        _journal.append(self.key, {"ops": [_wall("w1", 3000.0)]})
        import json
        import struct
        blob, _ = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        head_len = struct.unpack_from("<I", blob, 8)[0]
        self.assertTrue(json.loads(blob[12:12 + head_len].decode())["partial"])


class TheSignatureIgnoresOrderButNotContent(ButtonBase):
    """НАЙДЕНО ПРОВЕРКОЙ ДО ПОСТАВКИ, а не после.

    Целая сцена перечисляет элементы «сначала все тела, потом все призраки»,
    склейка — «тела и призраки базы, затем тела и призраки хвоста». Здание
    ОДНО И ТО ЖЕ, порядок в буфере разный. Первая редакция подписи была
    цепочкой хешей и объявила эти два здания разными; `verify_shown.mjs`
    поймал это на третьей проверке.

    Порядок в буфере — деталь рисования, а не свойство здания. Поэтому подпись
    складывается МУЛЬТИМНОЖЕСТВОМ (сумма sha256 по модулю 2^256), и она обязана
    не замечать порядок, но замечать всё остальное.
    """

    def test_the_same_elements_in_any_order_sign_the_same(self):
        key_a, key_b = ("сумма", "а"), ("сумма", "б")
        _showroom.forget(key_a)
        _showroom.forget(key_b)
        records = [b"first", b"second", b"third"]
        a = _showroom.scene_shown(key_a, records, elements=3, whole=True)
        b = _showroom.scene_shown(key_b, list(reversed(records)), elements=3,
                                  whole=True)
        self.assertEqual(a, b)

    def test_a_duplicate_element_changes_the_signature(self):
        """СУММА, а не XOR: XOR погасил бы пару, и элемент, продублированный
        склейкой, исчез бы бесследно — ровно тот дефект, который подпись
        обязана ловить."""
        key_a, key_b = ("сумма", "в"), ("сумма", "г")
        _showroom.forget(key_a)
        _showroom.forget(key_b)
        one = _showroom.scene_shown(key_a, [b"x", b"y"], elements=2, whole=True)
        two = _showroom.scene_shown(key_b, [b"x", b"y", b"y"], elements=3,
                                    whole=True)
        self.assertNotEqual(one, two)

    def test_two_identical_records_do_not_cancel(self):
        key = ("сумма", "д")
        _showroom.forget(key)
        empty = _showroom.scene_reset(key)
        pair = _showroom.scene_shown(key, [b"same", b"same"], elements=2,
                                     whole=True)
        self.assertNotEqual(pair, empty)

    def test_a_whole_scene_resets_the_accumulation(self):
        """База заменяет всё, что панель держала до неё; хвост — дописывается.
        Иначе перезагрузка сцены удваивала бы здание в подписи."""
        key = ("сумма", "е")
        _showroom.forget(key)
        first = _showroom.scene_shown(key, [b"a"], elements=1, whole=True)
        _showroom.scene_shown(key, [b"b"], elements=1, whole=False)
        again = _showroom.scene_shown(key, [b"a"], elements=1, whole=True)
        self.assertEqual(first, again)

    def test_an_empty_scene_has_a_signature_of_its_own(self):
        """«Ничего не показано» — состояние, у которого есть подпись. Отличать
        его от «сессии нет» обязано значение, а не его отсутствие."""
        key = ("сумма", "ж")
        _showroom.forget(key)
        self.assertEqual(_showroom.scene_digest(key), "")
        self.assertTrue(_showroom.scene_reset(key))
        self.assertNotEqual(_showroom.scene_digest(key), "")


class TheCostStaysOffTheFramePath(ButtonBase):
    """Замер, ради которого волна проверялась: 300 программ, дельта БЕЗ
    подписи 1.9 мс, С подписью 2.0 мс. Полный пересчёт подписи стоил бы
    8.5 мс на кадр — то есть починили бы транспорт и сломали бы его кнопкой."""

    def test_the_digest_is_accumulated_not_recomputed(self):
        import inspect
        source = inspect.getsource(_showroom.scene_shown)
        self.assertIn("scene.total", source)
        self.assertNotIn("build_program_preview", source)

    def test_a_frame_only_folds_its_own_elements(self):
        """Кадр обязан складывать РОВНО свои записи. Если бы он трогал чужие,
        стоимость кадра снова зависела бы от возраста сессии."""
        key = ("цена", "а")
        _showroom.forget(key)
        _showroom.scene_shown(key, [b"x"] * 100, elements=100, whole=True)
        before = _showroom.scene_stats(key)["records_bytes"]
        _showroom.scene_shown(key, [b"y"] * 5, elements=5, whole=False)
        after = _showroom.scene_stats(key)["records_bytes"]
        self.assertEqual(after - before, 5)


class TheClientSideSignatureIsCheckedByNode(unittest.TestCase):
    """Подпись НАРИСОВАННОГО считает панель, и питоном её не проверить.

    `verify_shown.mjs` рядом с этим файлом считает подпись клиентским кодом по
    склеенной сцене и сверяет с накопленной сервером. Совпадение имеет смысл
    ровно потому, что вычисления НЕЗАВИСИМЫ: повтори панель серверное значение
    — и подпись означала бы вежливость, а не равенство.
    """

    def test_the_checker_ships_with_the_tests(self):
        import pathlib
        tool = pathlib.Path(__file__).with_name("verify_shown.mjs")
        self.assertTrue(tool.exists())
        text = tool.read_text(encoding="utf-8")
        self.assertIn("shownDigest", text)
        self.assertIn("склейка == целое-после", text)

    def test_the_client_does_not_echo_the_server_value(self):
        """Панель обязана СЧИТАТЬ подпись, а не переписывать её из заголовка.
        Иначе подписывалось бы намерение сервера вместо результата на экране."""
        import pathlib
        path = pathlib.Path("/opt/kukai-rebuild1/assets/viewer/viewer.js")
        if not path.exists():
            self.skipTest("клиентские файлы не развёрнуты")
        text = path.read_text(encoding="utf-8")
        self.assertIn("await shownDigest(data)", text)
        self.assertNotIn("shown_digest: data.header.shown_digest", text)

    def test_the_schema_string_matches_on_both_sides(self):
        """Строка схемы дублируется значением, чтобы клиентский модуль остался
        без зависимостей. Дублирование законно ровно пока его держит тест."""
        import pathlib
        path = pathlib.Path("/opt/kukai-rebuild1/assets/viewer/scene-data.js")
        if not path.exists():
            self.skipTest("клиентские файлы не развёрнуты")
        self.assertIn(_showroom.SCENE_SCHEMA,
                      path.read_text(encoding="utf-8"))
