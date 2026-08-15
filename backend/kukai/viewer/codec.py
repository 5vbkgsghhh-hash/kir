"""КОДЕК СЦЕНЫ — почему это байты, а не JSON, и почему инстансы, а не меши.

ЗАМЕР, ЗАДАВШИЙ ФОРМАТ (10.08.2026, `демо-v3`, 84 120 оболочек):

| представление                                   | размер   |
|-------------------------------------------------|---------:|
| наивный JSON (оболочка целиком на элемент)      | 22.08 МБ |
| он же, gzip -6                                  |  1.92 МБ |
| ЭТОТ формат (инстансы + таблицы строк)          |  3.46 МБ |
| из них геометрия                                |  2.11 МБ |
| из них адреса элементов (строки)                |  0.76 МБ |

`snowdon_plumb_v4`, 31 904 оболочки: JSON 7.55 МБ, этот формат 1.31 МБ.

Наивный JSON проигрывает не размером — он проигрывает ТЕМ, ЧТО С НИМ ДЕЛАЕТ
БРАУЗЕР. 22 МБ текста это разбор в главном потоке и 84 120 объектов в куче;
здесь же браузер получает `ArrayBuffer` и делает из него `Float32Array` без
единого разбора, а затем отдаёт его прямо в `InstancedMesh`. Разница не в
мегабайтах, а в том, что второе не блокирует кадр.

ПОЧЕМУ ИНСТАНСИНГ С ПЕРВОГО ДНЯ, А НЕ «ПОТОМ ОПТИМИЗИРУЕМ». 84 120 отдельных
мешей — это 84 120 draw call, то есть заведомо мёртвая сцена на любом железе.
Инстансинг переводит их в ТРИ вызова (ящики, капсулы, призмы), потому что
ящик у всех один и тот же — меняется только матрица. Переписать сцену на
инстансы позже дороже, чем начать с них: на инстансах держится и формат
данных, и способ раскраски (`instanceColor`), и выбор мышью (`instanceId`).

ФОРМАТ. Заголовок — JSON (там таблицы строк и смещения), тело — буферы
подряд. Никакого выравнивания сверх естественного: все буферы кратны 4 байтам
и укладываются в порядке убывания размера элемента, поэтому `Float32Array`
над `ArrayBuffer` строится без копирования.

    "KIRSCN01"          8 байт, магия
    header_len          uint32 LE
    header_json         header_len байт, utf-8, ДОПОЛНЕН ПРОБЕЛАМИ до того,
                        чтобы 12 + header_len делилось на 4
    <буферы подряд, в порядке объявления в header["buffers"]>

ВЫРАВНИВАНИЕ — НЕ ПЕДАНТИЗМ, А УСЛОВИЕ РАБОТОСПОСОБНОСТИ. `new Float32Array(
buffer, offset, len)` в браузере ТРЕБУЕТ, чтобы `offset` делился на 4, и
бросает `RangeError` иначе. Длина заголовка произвольна (в неё едут таблицы
строк и перепись), поэтому без добивки тело начиналось бы со случайного
байта и КАЖДЫЙ разбор падал бы — на демо-v3 заголовок дал base % 4 == 3.
Добивка идёт ПРОБЕЛАМИ: пробел законен в JSON, поэтому клиент разбирает
заголовок, ничего не зная про добивку.

Порядок буферов тоже несущий и идёт ПО УБЫВАНИЮ ШАГА: сначала всё кратное
четырём (box 24, capsule 28, prism_* 8/8/4, elem_slot 4), потом двухбайтовое
(elem_cat, elem_level), потом однобайтовое, потом строки. При выровненном
начале это даёт выровненное начало каждому буферу без единого байта добивки
между ними — и это проверяется тестом, а не обещается.

ЧТО ЗДЕСЬ НЕ ЛЕЖИТ И ПОЧЕМУ. Треугольников нет ни одного: их строит клиент из
примитивов (ящик — один `BoxGeometry`, капсула — один `CapsuleGeometry`,
призма — экструзия подошвы). Класть сюда треугольники значило бы утроить
трафик ради работы, которую GPU делает даром.

ЕДИНИЦЫ. Всё в МИЛЛИМЕТРАХ, как во всём пакете (`clash.geom`: «модели
приезжают из Revit в футах и переводятся в мм»). Клиент масштабирует сам —
здесь пересчёта нет намеренно, иначе появилось бы второе место, где живёт
единица длины.

ТОЧНОСТЬ. `float32` на координатах в миллиметрах: 24 бита мантиссы дают
точное представление целых до 16 777 216 мм = 16.7 км. Здание такого размера
не бывает; здание, УДАЛЁННОЕ от начала координат на такое расстояние, бывает
(площадка в геодезической системе). Поэтому кодек ВЫЧИТАЕТ общее начало
(`header["origin_mm"]`) и пишет смещения от него — тогда 24 бита ложатся на
размер здания, а не на расстояние до Гринвича. Начало публикуется в
заголовке, а не подразумевается.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, field
from typing import Any, Sequence

__all__ = ("SCENE_MAGIC", "SCENE_SCHEMA", "SceneBuilder", "encode_scene")

SCENE_MAGIC = b"KIRSCN01"
SCENE_SCHEMA = "kir-viewer-scene/1"

#: Размер одной записи каждого потока, в байтах. Публикуется в заголовке, а не
#: зашивается в клиенте: клиент, который «знает» шаг, разъедется с сервером
#: молча на первом же добавленном поле.
STRIDE = {
    "box": 24,      # cx cy cz hx hy hz            (6 × float32)
    "capsule": 28,  # x0 y0 z0 x1 y1 z1 r          (7 × float32)
    "prism_z": 8,   # z0 z1                        (2 × float32)
    "prism_xy": 8,  # x y                          (2 × float32)
    "prism_ofs": 4,                                # uint32
    "elem_kind": 1,                                # uint8
    "elem_slot": 4,                                # uint32
    "elem_cat": 2,                                 # uint16
    "elem_level": 2,                               # uint16
    "elem_trust": 1,                               # uint8
    "elem_fidelity": 1,                            # uint8
    # Оси, по которым НИКТО НЕ ОБЕЩАЛ ПРОВЕРЯТЬ — тристейтом в одном байте:
    # 0 = все три объявлены, маска = по этим осям обязательств нет,
    # 255 = судить нечем. Отдельный буфер, а не бит в `elem_fidelity`:
    # это ДРУГОЙ вопрос (не «точна ли форма», а «бралась ли ось проверяться»),
    # и склеивать их значило бы повторить ровно ту склейку, из-за которой
    # `unwitnessed_axes` пришлось заводить отдельно от зелёной тройки.
    "elem_axes": 1,                                # uint8
    # ЛИНИЯ АВТОРИТЕТА И СУЩЕСТВОВАНИЕ — две оси графа здания, и обе
    # ортогональны точности формы. `existence=planned` значит «элемента в
    # Revit ещё нет», а не «форма его неизвестна»: инженер три часа строит
    # здание, которого в документе нет, и спутать это с построенным значит
    # превратить кнопку «отправить в Revit» в лотерею.
    "elem_authority": 1,                           # uint8
    "elem_existence": 1,                           # uint8
    # Факты О РЕБРЕ, отнесённые к его концу: опровергнутое отношение, цель
    # вне извлечения. Именно факты о ребре, а не о самом элементе.
    "elem_flags": 1,                               # uint8
}

#: Числовые коды примитивов. Клиент читает их из заголовка (`header["kinds"]`),
#: а не из своей копии этой таблицы.
KIND_BOX, KIND_CAPSULE, KIND_PRISM = 0, 1, 2

#: Разделители записи подписи. Байтами, а не литералами со
#: спецсимволами: исходник с настоящим нулевым байтом внутри
#: Python не разбирает вовсе, и это уже случилось однажды.
_RECORD_TAG = bytes((1,))
_FIELD_SEP = bytes((0,))

#: Дублируются из `honesty` ЗНАЧЕНИЕМ, а не импортом: кодек обязан остаться
#: чистым stdlib (он не знает ни про `clash`, ни про `ir`), а согласованность
#: держится тестом `test_codec.py::AxesContractMatchesHonesty`, а не надеждой.
_AXES_ORDER = ("geometry", "topology", "semantic")
_AXES_UNJUDGEABLE = 255


def _f32_safe(value: float) -> float:
    """Не конечное число в буфере — это NaN в вершине и чёрный экран без
    единого сообщения. Здесь оно превращается в ноль, и вызывающий обязан был
    отсеять такой элемент раньше (`snapshot.validate` это и делает)."""
    return float(value) if math.isfinite(value) else 0.0


@dataclass
class SceneBuilder:
    """Накопитель сцены. Пишет ПАРАЛЛЕЛЬНЫЕ потоки, а не список объектов.

    Параллельность — не микрооптимизация, а требование `InstancedMesh`:
    матрицы одного инстансированного меша обязаны лежать сплошным куском.
    Поэтому элемент разложен на «в каком потоке он лежит» (`elem_kind`) и «под
    каким номером» (`elem_slot`), а его атрибуты едут отдельными массивами.
    """

    origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)

    box: bytearray = field(default_factory=bytearray)
    capsule: bytearray = field(default_factory=bytearray)
    prism_z: bytearray = field(default_factory=bytearray)
    prism_xy: bytearray = field(default_factory=bytearray)
    prism_ofs: bytearray = field(default_factory=bytearray)

    elem_kind: bytearray = field(default_factory=bytearray)
    elem_slot: bytearray = field(default_factory=bytearray)
    elem_cat: bytearray = field(default_factory=bytearray)
    elem_level: bytearray = field(default_factory=bytearray)
    elem_trust: bytearray = field(default_factory=bytearray)
    elem_fidelity: bytearray = field(default_factory=bytearray)
    elem_axes: bytearray = field(default_factory=bytearray)
    elem_authority: bytearray = field(default_factory=bytearray)
    elem_existence: bytearray = field(default_factory=bytearray)
    elem_flags: bytearray = field(default_factory=bytearray)

    ids: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    #: ЗАПИСИ ПОДПИСИ — ПО ОДНОЙ НА ЭЛЕМЕНТ, списком, а не сплошным потоком.
    #: Поэлементно намеренно: подпись показанного складывается МУЛЬТИМНОЖЕСТВОМ
    #: и потому не зависит от порядка (см. `showroom.scene_shown`).
    records: list = field(default_factory=list)

    _cats: dict[str, int] = field(default_factory=dict)
    _levels: dict[str, int] = field(default_factory=dict)
    _n_box: int = 0
    _n_cap: int = 0
    _n_prism: int = 0
    _prism_vert: int = 0

    def __post_init__(self) -> None:
        # Смещения призм — префиксные суммы, поэтому первый элемент = 0 и
        # пишется сразу: без него у первой призмы не было бы начала.
        self.prism_ofs += struct.pack("<I", 0)

    # ── таблицы строк ──────────────────────────────────────────────────────
    def _cat_id(self, name: str) -> int:
        key = name or "?"
        if key not in self._cats:
            self._cats[key] = len(self._cats)
        return self._cats[key]

    def _level_id(self, name: str | None) -> int:
        key = str(name) if name is not None else "?"
        if key not in self._levels:
            self._levels[key] = len(self._levels)
        return self._levels[key]

    # ── примитивы ──────────────────────────────────────────────────────────
    def add_box(self, lo: Sequence[float], hi: Sequence[float]) -> tuple[int, int]:
        """Габаритный бокс -> центр и ПОЛУразмеры. Полуразмеры, а не размеры,
        потому что `BoxGeometry(1,1,1)` в three.js центрирована, и масштаб
        инстанса умножается ровно на них."""
        ox, oy, oz = self.origin_mm
        cx = _f32_safe((lo[0] + hi[0]) * 0.5 - ox)
        cy = _f32_safe((lo[1] + hi[1]) * 0.5 - oy)
        cz = _f32_safe((lo[2] + hi[2]) * 0.5 - oz)
        # ПОЛУРАЗМЕР НЕ ЗАЖИМАЕТСЯ СНИЗУ. Вырожденная оболочка (плоскость,
        # линия, точка) обязана остаться вырожденной: раздуть её до
        # видимой — значит нарисовать объём, которого в данных нет. На
        # `демо-v3` это 38.2 % элементов, и они помечены `DEGENERATE`,
        # а вьюер рисует их отдельным материалом, а не отдельной толщиной.
        hx = _f32_safe(abs(hi[0] - lo[0]) * 0.5)
        hy = _f32_safe(abs(hi[1] - lo[1]) * 0.5)
        hz = _f32_safe(abs(hi[2] - lo[2]) * 0.5)
        self.box += struct.pack("<6f", cx, cy, cz, hx, hy, hz)
        slot = self._n_box
        self._n_box += 1
        return KIND_BOX, slot

    def add_capsule(self, path: Sequence[Sequence[float]],
                    radius: float) -> tuple[int, int]:
        """Полилиния × радиус -> по инстансу на СЕГМЕНТ.

        Капсула из N точек это N-1 сегмент, и каждый едет своим инстансом:
        `CapsuleGeometry` умеет только один отрезок. Узлы при этом покрыты
        дважды (полусферы соседних сегментов совпадают) — ровно так же, как
        в `clash.geom.Capsule`, где тело есть ОБЪЕДИНЕНИЕ сегментов.

        Элемент занимает слоты `slot .. slot+n-1`; число сегментов вьюер
        берёт из следующего элемента того же потока, поэтому первый слот и
        есть адрес элемента.
        """
        ox, oy, oz = self.origin_mm
        first = self._n_cap
        pts = list(path)
        if len(pts) == 1:
            pts = [pts[0], pts[0]]
        for a, b in zip(pts, pts[1:]):
            self.capsule += struct.pack(
                "<7f",
                _f32_safe(a[0] - ox), _f32_safe(a[1] - oy), _f32_safe(a[2] - oz),
                _f32_safe(b[0] - ox), _f32_safe(b[1] - oy), _f32_safe(b[2] - oz),
                _f32_safe(radius))
            self._n_cap += 1
        return KIND_CAPSULE, first

    def add_prism(self, pieces: Sequence[Sequence[Sequence[float]]],
                  z0: float, z1: float) -> tuple[int, int]:
        """Выпуклые куски подошвы × [z0, z1].

        Куски пишутся ПОДРЯД и каждый получает свою запись `prism_z`, поэтому
        `PrismSet` (вогнутая область как объединение выпуклых) и одиночная
        `Prism` кодируются одинаково — разница только в числе кусков. Это не
        упрощение: у `PrismSet` общий размах по Z по построению
        (`clash.geom.PrismSet`: «подошва выдавливается одной отметкой на одну
        высоту»), и второго Z у куска взять неоткуда.
        """
        ox, oy, oz = self.origin_mm
        first = self._n_prism
        for piece in pieces:
            for x, y in piece:
                self.prism_xy += struct.pack(
                    "<2f", _f32_safe(x - ox), _f32_safe(y - oy))
                self._prism_vert += 1
            self.prism_ofs += struct.pack("<I", self._prism_vert)
            self.prism_z += struct.pack(
                "<2f", _f32_safe(z0 - oz), _f32_safe(z1 - oz))
            self._n_prism += 1
        return KIND_PRISM, first

    # ── элемент ────────────────────────────────────────────────────────────
    def _record(self, *, element_id: str, category: str, level: str | None,
                label: str, kind: int, slot: int, trust: int, fidelity: int,
                axes: int, authority: int, existence: int, flags: int) -> None:
        """Одна запись ПОДПИСИ ПОКАЗАННОГО. Формат — спецификация, а не деталь.

        ЗАЧЕМ ЭТО ЗДЕСЬ. Кнопка «отправить в Revit» подписывает ТО, ЧТО ЧЕЛОВЕК
        ВИДЕЛ. Пока сцена приезжала целиком, «показанное» и «переносимое»
        совпадали по построению. Со склейкой это два РАЗНЫХ вычисления —
        серверное и клиентское, — и любое их расхождение есть здание, которого
        инженер не видел, построенное с его согласия.

        Поэтому запись собирается из тех же значений, что кормят рисовальщик, и
        только из них: адрес, РАЗРЕШЁННЫЕ строки категории и уровня (не их
        номера — номера у склейки свои), подпись операции, обе оси честности,
        обе оси графа, флаги рёбер и СОБСТВЕННАЯ ГЕОМЕТРИЯ элемента, взятая по
        слоту ровно так, как её возьмёт `build()`.

        НОМЕРА В ТАБЛИЦАХ НЕ ВХОДЯТ НАМЕРЕННО. Склейка переиндексирует
        категории и уровни (у дельты свои номера), поэтому подпись по номерам
        расходилась бы у двух сторон, ничего не значащим отличием.
        """
        blob = bytearray(_RECORD_TAG)
        for text in (element_id, category, str(level or ""), label):
            blob += text.encode("utf-8")
            blob += _FIELD_SEP
        blob += bytes((kind & 0xFF, trust & 0xFF, fidelity & 0xFF, axes & 0xFF,
                       authority & 0xFF, existence & 0xFF, flags & 0xFF))
        # ГЕОМЕТРИЯ БЕРЁТСЯ ПО СЛОТУ И ДО ТЕКУЩЕГО КОНЦА ПОТОКА: у капсулы это
        # ВСЕ её сегменты, у призмы — ВСЕ её куски. Подписать только первый
        # значило бы не заметить, что у ломаной пропала половина.
        if kind == KIND_BOX:
            blob += self.box[slot * 24:(slot + 1) * 24]
        elif kind == KIND_CAPSULE:
            blob += self.capsule[slot * 28:self._n_cap * 28]
        elif kind == KIND_PRISM:
            blob += self.prism_z[slot * 8:self._n_prism * 8]
            v0 = struct.unpack_from("<I", self.prism_ofs, slot * 4)[0]
            v1 = struct.unpack_from("<I", self.prism_ofs, self._n_prism * 4)[0]
            blob += self.prism_xy[v0 * 8:v1 * 8]
        self.records.append(bytes(blob))

    def add_element(self, *, element_id: str, category: str,
                    level: str | None, trust: int, fidelity: int,
                    kind: int, slot: int, label: str = "",
                    axes: int = 255, authority: int = 2, existence: int = 2,
                    flags: int = 0) -> None:
        """`axes` по умолчанию 255 = «судить нечем», а НЕ 0 = «всё объявлено».

        Умолчание выбрано так намеренно: вызывающий, забывший передать оси,
        получит серое «не смотрели», а не зелёное «проверено». Умолчание,
        ошибающееся в сторону зелёного, — это тот же дефект, что и молчащий
        свидетель, только спрятанный в сигнатуре.

        `authority` и `existence` по умолчанию 2 = «неизвестно» по той же
        причине: сцена, построенная без слоя графа, обязана говорить «не
        спрашивали», а не выдавать всё за уже построенное.
        """
        self.ids.append(element_id)
        self.labels.append(label)
        self.elem_kind += struct.pack("<B", kind)
        self.elem_slot += struct.pack("<I", slot)
        self.elem_cat += struct.pack("<H", self._cat_id(category))
        self.elem_level += struct.pack("<H", self._level_id(level))
        self.elem_trust += struct.pack("<B", trust)
        self.elem_fidelity += struct.pack("<B", fidelity)
        self.elem_axes += struct.pack("<B", axes)
        self.elem_authority += struct.pack("<B", authority)
        self.elem_existence += struct.pack("<B", existence)
        self.elem_flags += struct.pack("<B", flags)
        self._record(element_id=element_id, category=category, level=level,
                     label=label, kind=kind, slot=slot, trust=trust,
                     fidelity=fidelity, axes=axes, authority=authority,
                     existence=existence, flags=flags)

    @property
    def count(self) -> int:
        return len(self.ids)

    def shown_records(self) -> list[bytes]:
        """Записи подписи элементов ЭТОЙ сцены — по одной на элемент.

        Отдаются списком, а не дайджестом: подпись сессии складывается по всем
        показанным сценам, и складывать её обязан тот, кто помнит сессию
        (`live.showroom`), а не тот, кто пакует один кадр.
        """
        return list(self.records)

    def finish(self, meta: dict[str, Any]) -> bytes:
        """Заголовок + тело. Порядок буферов фиксируется ЗДЕСЬ и публикуется —
        клиент читает `header["buffers"]`, а не помнит порядок."""
        ids_blob = "\n".join(self.ids).encode("utf-8")
        labels_blob = "\n".join(self.labels).encode("utf-8")
        streams: list[tuple[str, bytes]] = [
            ("box", bytes(self.box)),
            ("capsule", bytes(self.capsule)),
            ("prism_z", bytes(self.prism_z)),
            ("prism_xy", bytes(self.prism_xy)),
            ("prism_ofs", bytes(self.prism_ofs)),
            ("elem_slot", bytes(self.elem_slot)),
            ("elem_cat", bytes(self.elem_cat)),
            ("elem_level", bytes(self.elem_level)),
            ("elem_kind", bytes(self.elem_kind)),
            ("elem_trust", bytes(self.elem_trust)),
            ("elem_fidelity", bytes(self.elem_fidelity)),
            ("elem_axes", bytes(self.elem_axes)),
            ("elem_authority", bytes(self.elem_authority)),
            ("elem_existence", bytes(self.elem_existence)),
            ("elem_flags", bytes(self.elem_flags)),
            ("ids", ids_blob),
            ("labels", labels_blob),
        ]
        buffers: list[dict[str, Any]] = []
        offset = 0
        for name, blob in streams:
            buffers.append({"name": name, "offset": offset, "length": len(blob),
                            "stride": STRIDE.get(name, 1)})
            offset += len(blob)

        header = dict(meta)
        header.update({
            "schema": SCENE_SCHEMA,
            "origin_mm": list(self.origin_mm),
            "units": "mm",
            "elements": self.count,
            "counts": {"box": self._n_box, "capsule": self._n_cap,
                       "prism": self._n_prism},
            "kinds": {"box": KIND_BOX, "capsule": KIND_CAPSULE,
                      "prism": KIND_PRISM},
            # Порядок битов `elem_axes` и значение «судить нечем» публикуются:
            # клиент, который держал бы свою копию, разъехался бы с сервером
            # на первой же новой оси у владельца таблицы обязательств.
            "axes_order": list(_AXES_ORDER),
            "axes_unjudgeable": _AXES_UNJUDGEABLE,
            "categories": [n for n, _ in sorted(self._cats.items(),
                                                key=lambda kv: kv[1])],
            "levels": [n for n, _ in sorted(self._levels.items(),
                                            key=lambda kv: kv[1])],
            "buffers": buffers,
            "body_bytes": offset,
        })
        header_json = json.dumps(header, ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
        # ДОБИВКА ЗАГОЛОВКА ДО ВЫРАВНИВАНИЯ ТЕЛА. Без неё `new Float32Array(
        # buffer, offset, …)` бросает RangeError, потому что offset обязан
        # делиться на 4. Пробел — законный JSON, поэтому разбор заголовка о
        # добивке знать не обязан. Замер: на демо-v3 без неё base % 4 == 3.
        pad = (-(len(SCENE_MAGIC) + 4 + len(header_json))) % 4
        header_json += b" " * pad
        out = bytearray(SCENE_MAGIC)
        out += struct.pack("<I", len(header_json))
        out += header_json
        for _, blob in streams:
            out += blob
        return bytes(out)


def encode_scene(builder: SceneBuilder, meta: dict[str, Any]) -> bytes:
    return builder.finish(meta)
