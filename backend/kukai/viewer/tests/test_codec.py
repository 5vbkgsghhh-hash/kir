"""Контракт байтов сцены. Каждый тест — ОПРОВЕРЖЕНИЕ конкретного способа
соврать картинкой, а не проверка того, что код исполнился.

Замер, ради которого формат такой (10.08.2026, демо-v3, 84 120 оболочек):
наивный JSON 22.08 МБ против 4.84 МБ здесь (0.77 МБ после gzip). Байты
выиграли не размером, а тем, что браузер не разбирает 84 120 объектов в
главном потоке.
"""

import json
import struct
import unittest

from kukai.viewer.codec import SCENE_MAGIC, STRIDE, SceneBuilder


def _decode(blob):
    assert blob[:8] == SCENE_MAGIC
    head_len = struct.unpack_from("<I", blob, 8)[0]
    header = json.loads(blob[12:12 + head_len].decode("utf-8"))
    return header, 12 + head_len


class CodecShape(unittest.TestCase):

    def test_header_declares_the_exact_body_length(self):
        """Заголовок, который врёт про длину тела, даёт клиенту сдвинутые
        буферы и МОЛЧА — картинка соберётся, просто не та."""
        builder = SceneBuilder()
        kind, slot = builder.add_box((0, 0, 0), (1000, 2000, 3000))
        builder.add_element(element_id="a", category="OST_Walls", level="L1",
                            trust=0, fidelity=2, kind=kind, slot=slot)
        blob = builder.finish({})
        header, base = _decode(blob)
        self.assertEqual(header["body_bytes"], len(blob) - base)
        self.assertEqual(
            header["body_bytes"],
            sum(b["length"] for b in header["buffers"]))

    def test_every_per_element_buffer_has_exactly_one_record_per_element(self):
        """Поэлементный буфер короче переписи — это элементы без атрибутов,
        то есть здание, часть которого не имеет состояния честности."""
        builder = SceneBuilder()
        for i in range(7):
            kind, slot = builder.add_box((i, 0, 0), (i + 1, 1, 1))
            builder.add_element(element_id=f"e{i}", category="OST_Walls",
                                level="L1", trust=0, fidelity=2,
                                kind=kind, slot=slot)
        header, _ = _decode(builder.finish({}))
        sizes = {b["name"]: b["length"] for b in header["buffers"]}
        for name in ("elem_kind", "elem_trust", "elem_fidelity", "elem_cat",
                     "elem_level", "elem_slot"):
            self.assertEqual(sizes[name], 7 * STRIDE[name], name)

    def test_capsule_of_n_points_makes_n_minus_one_instances(self):
        """Полилиния — ОБЪЕДИНЕНИЕ сегментов (`clash.geom.Capsule`). Один
        инстанс на всю полилинию нарисовал бы прямую там, где трасса ломаная."""
        builder = SceneBuilder()
        kind, slot = builder.add_capsule(
            [(0, 0, 0), (100, 0, 0), (100, 100, 0), (100, 100, 100)], 25.0)
        builder.add_element(element_id="p", category="OST_PipeCurves",
                            level="L1", trust=0, fidelity=1, kind=kind,
                            slot=slot)
        header, _ = _decode(builder.finish({}))
        self.assertEqual(header["counts"]["capsule"], 3)

    def test_single_point_capsule_still_produces_one_instance(self):
        """Вырожденная ось не имеет права ИСЧЕЗНУТЬ: пропавший элемент
        неотличим от элемента, которого не было."""
        builder = SceneBuilder()
        builder.add_capsule([(0, 0, 0)], 10.0)
        header, _ = _decode(builder.finish({}))
        self.assertEqual(header["counts"]["capsule"], 1)

    def test_prism_offsets_are_monotone_and_close_the_vertex_buffer(self):
        """Смещения — префиксные суммы. Немонотонные дают отрицательную длину
        куска, а незакрытые — молча обрезанную последнюю подошву."""
        builder = SceneBuilder()
        builder.add_prism((((0, 0), (10, 0), (10, 10)),
                           ((20, 20), (30, 20), (30, 30), (20, 30))), 0.0, 3000.0)
        blob = builder.finish({})
        header, base = _decode(blob)
        spans = {b["name"]: (base + b["offset"], b["length"])
                 for b in header["buffers"]}
        off, length = spans["prism_ofs"]
        values = struct.unpack_from(f"<{length // 4}I", blob, off)
        self.assertEqual(values[0], 0)
        self.assertTrue(all(values[i] <= values[i + 1]
                            for i in range(len(values) - 1)))
        self.assertEqual(values[-1] * STRIDE["prism_xy"],
                         spans["prism_xy"][1])

    def test_degenerate_box_keeps_its_zero_extent(self):
        """Габарит нулевого объёма — 38.2 % демо-v3. Раздуть его до видимого
        значило бы нарисовать объём, которого в данных нет."""
        builder = SceneBuilder()
        builder.add_box((0, 0, 500), (1000, 1000, 500))
        blob = builder.finish({})
        header, base = _decode(blob)
        off = next(base + b["offset"] for b in header["buffers"]
                   if b["name"] == "box")
        _, _, _, _, _, half_z = struct.unpack_from("<6f", blob, off)
        self.assertEqual(half_z, 0.0)

    def test_origin_is_published_not_implied(self):
        """Кодек вычитает общее начало, чтобы float32 лёг на размер здания, а
        не на расстояние до начала геодезической системы. Клиент обязан уметь
        вернуть абсолют — значит начало обязано ехать в заголовке."""
        builder = SceneBuilder(origin_mm=(1_000_000.0, 2_000_000.0, 0.0))
        builder.add_box((1_000_000.0, 2_000_000.0, 0.0),
                        (1_001_000.0, 2_001_000.0, 3000.0))
        header, base = _decode(builder.finish({}))
        self.assertEqual(header["origin_mm"], [1_000_000.0, 2_000_000.0, 0.0])
        self.assertEqual(header["units"], "mm")

    def test_ids_are_one_per_element_and_recoverable(self):
        builder = SceneBuilder()
        for name in ("11", "22", "33"):
            kind, slot = builder.add_box((0, 0, 0), (1, 1, 1))
            builder.add_element(element_id=name, category="OST_Walls",
                                level=None, trust=0, fidelity=2, kind=kind,
                                slot=slot)
        blob = builder.finish({})
        header, base = _decode(blob)
        span = next(b for b in header["buffers"] if b["name"] == "ids")
        text = blob[base + span["offset"]:
                    base + span["offset"] + span["length"]].decode("utf-8")
        self.assertEqual(text.split("\n"), ["11", "22", "33"])

class BodyIsAlignedForTypedArrays(unittest.TestCase):
    """ОПРОВЕРГАЮЩИЙ ТЕСТ ДЕФЕКТА 10.08, найденного проверкой на клиенте.

    Тело шло сразу за заголовком произвольной длины, поэтому `new
    Float32Array(buffer, offset, …)` бросал `RangeError: start offset of
    Float32Array should be a multiple of 4` — то есть КАЖДАЯ сцена не
    открывалась. На демо-v3 заголовок давал `base % 4 == 3`.

    Отдельно стыдное: комментарий кодека УТВЕРЖДАЛ, что виды строятся без
    копирования, и это было неправдой ровно того рода, против которой
    написан весь этот пакет. Комментарий — спецификация; спецификация,
    которую код не выполняет, — дефект, а не описка.
    """

    def _blob(self, elements):
        builder = SceneBuilder()
        for i in range(elements):
            kind, slot = builder.add_box((i, 0, 0), (i + 1, 1, 1))
            builder.add_element(element_id=f"e{i}",
                                category=f"OST_Cat{i % 3}",
                                level=f"L{i % 2}", trust=0, fidelity=2,
                                kind=kind, slot=slot,
                                label="тип " + "я" * (i % 7))
        return builder.finish({"run": "проба " + "х" * (elements % 11)})

    def test_body_starts_on_a_four_byte_boundary_for_any_header_length(self):
        """Длина заголовка произвольна: в неё едут таблицы строк и перепись.
        Перебор длин — единственный способ доказать, что добивка работает не
        случайно."""
        for elements in range(1, 40):
            blob = self._blob(elements)
            _, base = _decode(blob)
            self.assertEqual(base % 4, 0, f"elements={elements}")

    def test_every_four_byte_buffer_starts_aligned(self):
        """Мало выровнять начало тела: буфер, идущий за нечётным по длине
        соседом, съедет сам. Порядок буферов держит это, и проверяется он
        здесь, а не в комментарии."""
        for elements in (1, 5, 17, 33):
            blob = self._blob(elements)
            header, base = _decode(blob)
            for span in header["buffers"]:
                if span["stride"] in (4, 8, 24, 28):
                    self.assertEqual((base + span["offset"]) % 4, 0,
                                     f"{span[chr(110)+chr(97)+chr(109)+chr(101)]} elements={elements}")
                elif span["stride"] == 2:
                    self.assertEqual((base + span["offset"]) % 2, 0,
                                     f"elements={elements}")

    def test_padding_keeps_the_header_valid_json(self):
        """Добивка пробелами, а не нулями: нулевой байт сломал бы разбор
        заголовка, и сцена падала бы уже на JSON."""
        header, _ = _decode(self._blob(3))
        self.assertIsInstance(header, dict)
        self.assertIn("buffers", header)


class AxesRideOnEveryElement(unittest.TestCase):
    """Оси — ОТДЕЛЬНЫЙ буфер, а не бит в `elem_fidelity`.

    Вопросы разные: «точна ли форма» и «бралась ли ось проверяться». Склеить
    их значило бы повторить ровно ту склейку, из-за которой `unwitnessed_axes`
    пришлось заводить отдельно от зелёной тройки свидетеля.
    """

    def _blob(self, axes_values):
        builder = SceneBuilder()
        for i, axes in enumerate(axes_values):
            kind, slot = builder.add_box((i, 0, 0), (i + 1, 1, 1))
            builder.add_element(element_id=f"e{i}", category="OST_Walls",
                                level="L1", trust=0, fidelity=2, kind=kind,
                                slot=slot, axes=axes)
        return builder.finish({})

    def test_one_byte_per_element(self):
        blob = self._blob([0, 4, 255, 7])
        header, _ = _decode(blob)
        span = next(b for b in header["buffers"] if b["name"] == "elem_axes")
        self.assertEqual(span["length"], 4)
        self.assertEqual(span["stride"], 1)

    def test_values_survive_the_round_trip(self):
        values = [0, 1, 2, 4, 7, 255]
        blob = self._blob(values)
        header, base = _decode(blob)
        span = next(b for b in header["buffers"] if b["name"] == "elem_axes")
        raw = struct.unpack_from(f"<{len(values)}B", blob,
                                 base + span["offset"])
        self.assertEqual(list(raw), values)

    def test_the_default_is_unjudgeable_and_not_clean(self):
        """Вызывающий, забывший передать оси, обязан получить серое «не
        смотрели», а не зелёное «проверено». Умолчание, ошибающееся в сторону
        зелёного, — это молчащий свидетель, спрятанный в сигнатуре."""
        builder = SceneBuilder()
        kind, slot = builder.add_box((0, 0, 0), (1, 1, 1))
        builder.add_element(element_id="e", category="OST_Walls", level=None,
                            trust=0, fidelity=2, kind=kind, slot=slot)
        blob = builder.finish({})
        header, base = _decode(blob)
        span = next(b for b in header["buffers"] if b["name"] == "elem_axes")
        self.assertEqual(
            struct.unpack_from("<B", blob, base + span["offset"])[0], 255)

    def test_the_bit_order_is_published_for_the_client(self):
        """Клиент, державший бы свою копию порядка битов, разъехался бы с
        сервером на первой же новой оси у владельца таблицы обязательств."""
        header, _ = _decode(self._blob([0]))
        self.assertEqual(header["axes_order"],
                         ["geometry", "topology", "semantic"])
        self.assertEqual(header["axes_unjudgeable"], 255)


class AxesContractMatchesHonesty(unittest.TestCase):
    """Кодек дублирует порядок осей ЗНАЧЕНИЕМ, чтобы остаться чистым stdlib.

    Дублирование законно ровно до тех пор, пока его держит тест: без него
    `honesty` завела бы четвёртую ось, кодек продолжил бы публиковать три, и
    клиент читал бы чужие биты как свои — молча.
    """

    def test_order_and_sentinel_agree_with_the_vocabulary(self):
        from kukai.viewer import codec, honesty
        self.assertEqual(codec._AXES_ORDER, honesty.AXES_ORDER)
        self.assertEqual(codec._AXES_UNJUDGEABLE, honesty.AXES_UNJUDGEABLE)

    def test_the_sentinel_cannot_collide_with_a_real_mask(self):
        """Маска занимает столько бит, сколько осей. Сигнал «судить нечем»
        обязан лежать вне их диапазона, иначе три пропущенные оси читались бы
        как «не смотрели»."""
        from kukai.viewer import honesty
        self.assertGreater(honesty.AXES_UNJUDGEABLE,
                           (1 << len(honesty.AXES_ORDER)) - 1)
