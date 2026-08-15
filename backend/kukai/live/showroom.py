"""ВИТРИНА — то, что сервер ПОКАЗАЛ, слово в слово, под подписью содержимого.

ЗАЧЕМ ОНА ЕСТЬ, ОДНОЙ ФРАЗОЙ. Кнопка «перенести в Revit» обязана переносить
именно ту программу, которую человек видел на карточке. Проверять это
сравнением двух дайджестов — уже неплохо; сделать подмену НЕПРОИЗНОСИМОЙ —
лучше. Здесь второе: наружу уезжает ТОЛЬКО подпись, а исполнителю программу
выдаёт эта витрина и никто больше. Программы, которой не было на экране, у
панели нет способа назвать: у неё нет подписи в витрине.

ПОЧЕМУ НЕ ПОДОШЛА УЖЕ СУЩЕСТВУЮЩАЯ ПОДПИСЬ. `preview.FloorPlan.content_digest`
подписывает ЛИСТ, а не программу, — и это правильно для листа. Замер 04.08:

    стена 6000 мм по умолчанию,
    та же стена с height_mm=4200,
    та же стена с type_name="Кирпич 380"

дают ОДИН И ТОТ ЖЕ `content_digest` (48d11fe1d66eb6a8), потому что ни высота,
ни тип на плане не рисуются. Возьми мы его билетом на перенос — кнопка
«построить то, что вижу» строила бы кирпичную стену 4.2 м под подписью
обычной. Это ровно та вторая подпись у одного здания, ради запрета которой
компилятор и типизировали. Поэтому подпись переноса берёт ПРОГРАММУ целиком,
включая поля, которых на плане не видно.

ЕДИНИЦА ХРАНЕНИЯ — ПАЧКА, А НЕ СПИСОК ОПОВ. Здание есть ПАЧКА программ
(`compiler.PLAN_SOLO_OP`: лестница обязана быть единственным опом своей
программы), и границы программ на листе не видно. Витрина хранит их отдельно,
иначе перенос склеил бы пачку в одну программу и напоролся бы и на бюджет, и
на solo-правило.

ГРАНИЦЫ. Только stdlib. Ни одного импорта из `kukai.ir` — ни на уровне модуля,
ни ленивого, ни в комментарии-обещании. Витрина ничего не решает: она хранит
байты и умеет сказать, что они не менялись. Решает `transfer.py`, и он лежит
отдельно ИМЕННО ПОЭТОМУ: рисовальщик (`plan_stream`) обязан уметь наполнять
витрину, не приобретая при этом пути в компилятор.

ПРОГРАММЫ ХРАНЯТСЯ КАНОНИЧЕСКИМИ СТРОКАМИ, А НЕ СЛОВАРЯМИ. Три следствия, и
все три нужны: (1) выданная копия свежая и вызывающий не может испортить
оригинал; (2) подпись пересчитывается из самого хранимого, а не из его тени,
поэтому порча витрины ВИДНА; (3) байты считаются, значит потолок памяти можно
поставить в байтах, а не в «штуках неизвестного размера».
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

__all__ = (
    "SHOWROOM_SCHEMA",
    "Shown",
    "ShowroomEncodingError",
    "canonical_program",
    "forget",
    "levels",
    "program_digest",
    "recall",
    "scene_digest",
    "scene_reset",
    "scene_shown",
    "reset",
    "show",
    "stats",
)

SHOWROOM_SCHEMA = "kir-shown-program/1"


class ShowroomEncodingError(ValueError):
    """Программа не представима каноническим JSON — подписать её нечем."""


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _max_frames() -> int:
    """Сколько показанных кадров сессия помнит. Не «сколько влезет»: витрина
    живёт в памяти живого сервиса, и безлимитная витрина — это утечка с
    хорошим названием."""
    return _int_env("KUKAI_KIR_SHOWROOM_FRAMES", 12, low=1, high=512)


def _max_bytes() -> int:
    """Потолок в БАЙТАХ, а не в кадрах: кадр этажа с 1 500 опов и кадр с
    тремя стенами занимают разное, и считать их одинаково значит не считать."""
    return _int_env("KUKAI_KIR_SHOWROOM_BYTES", 4_000_000,
                    low=64_000, high=200_000_000)


def _max_sessions() -> int:
    return _int_env("KUKAI_KIR_SHOWROOM_SESSIONS", 8, low=1, high=256)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ShowroomEncodingError(str(exc)) from exc


def canonical_program(ops: Iterable[Mapping[str, Any]]) -> str:
    """Одна программа -> канонический JSON её операций."""
    return _canonical([dict(op) for op in ops])


def program_digest(programs: Sequence[str], context: str = "[]",
                   level: str = "") -> str:
    """ПОДПИСЬ ПОКАЗАННОГО. Считается из канонических строк, то есть ровно из
    того, что хранится и будет выдано исполнителю, — не из их копии.

    В подпись входит и `level`: один и тот же набор программ, показанный как
    план первого этажа и как план второго, — это два разных увиденных, и
    сливать их в одну подпись значило бы разрешить перенос «того же самого, но
    с другого листа».
    """
    return hashlib.sha256(_canonical({
        "schema": SHOWROOM_SCHEMA,
        "level": level,
        "context": context,
        "programs": list(programs),
    }).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Shown:
    """Один показанный кадр. Неизменяем; операции выдаются свежими копиями."""

    digest: str
    level: str
    seq: int
    ts: float
    #: Канонический JSON КАЖДОЙ программы пачки, в порядке журнала.
    programs_json: tuple[str, ...]
    #: Канонический JSON датумов. Это КОНТЕКСТ РИСОВАНИЯ, а не программа:
    #: `create_level` из шапки чанка приезжает сюда, чтобы этаж не потерял имя,
    #: но исполнять его отдельной программой нельзя — он уже внутри своих.
    context_json: str
    #: `census.to_dict()` листа, на котором это было показано. Едет вместе с
    #: программой намеренно: картинка без переписи — красивая неправда.
    census: Mapping[str, Any]
    intent: str = ""

    @property
    def nbytes(self) -> int:
        return sum(len(p) for p in self.programs_json) + len(self.context_json)

    def programs(self) -> list[list[dict[str, Any]]]:
        """Свежие изменяемые копии. Портить оригинал вызывающему нечем."""
        return [json.loads(blob) for blob in self.programs_json]

    def context(self) -> list[dict[str, Any]]:
        return json.loads(self.context_json)

    def render_ops(self) -> list[dict[str, Any]]:
        """Ровно тот список, который ушёл в рисовальщик."""
        ops = self.context()
        for program in self.programs():
            ops.extend(program)
        return ops

    @property
    def op_count(self) -> int:
        return sum(len(json.loads(blob)) for blob in self.programs_json)

    def verify(self) -> bool:
        """Пересчитать подпись из хранимого. Ложь = витрину подменили."""
        return program_digest(
            self.programs_json, self.context_json, self.level) == self.digest


@dataclass(slots=True)
class _Room:
    frames: "OrderedDict[str, Shown]"
    #: этаж -> подпись САМОГО СВЕЖЕГО показанного кадра. Нужна не для проверки,
    #: а для честного отказа: «этой программы я не показывал, а вот что на этом
    #: этаже сейчас» полезнее, чем «нет».
    latest: dict[str, str]
    held_bytes: int = 0
    shown_total: int = 0
    evicted: int = 0


_LOCK = threading.Lock()
_ROOMS: "OrderedDict[tuple[str, str], _Room]" = OrderedDict()


def show(key: tuple[str, str], *, level: str,
         programs: Sequence[Sequence[Mapping[str, Any]]],
         context: Sequence[Mapping[str, Any]] = (),
         census: Mapping[str, Any] | None = None,
         seq: int = 0, ts: float = 0.0, intent: str = "") -> Shown | None:
    """Положить показанное в витрину. Возвращает `Shown` или None, если
    класть нечего. Никогда не бросает: витрина не имеет права ломать кадр.
    """
    try:
        blobs = tuple(canonical_program(ops) for ops in programs if ops)
        if not blobs:
            return None
        ctx = canonical_program(context)
        digest = program_digest(blobs, ctx, level)
        entry = Shown(
            digest=digest, level=str(level), seq=int(seq), ts=float(ts),
            programs_json=blobs, context_json=ctx,
            census=dict(census or {}), intent=str(intent or "")[:200])
    except Exception:  # noqa: BLE001 — некодируемая программа не роняет поток
        return None
    with _LOCK:
        room = _ROOMS.get(key)
        if room is None:
            room = _Room(frames=OrderedDict(), latest={})
            _ROOMS[key] = room
            while len(_ROOMS) > _max_sessions():
                _ROOMS.popitem(last=False)
        _ROOMS.move_to_end(key)
        room.shown_total += 1
        room.latest[entry.level] = digest
        if digest in room.frames:
            # Кадр не изменился (перерисовка того же). Освежаем позицию в LRU,
            # но НЕ переписываем — хранимое обязано быть тем же байтом.
            room.frames.move_to_end(digest)
            return room.frames[digest]
        room.frames[digest] = entry
        room.held_bytes += entry.nbytes
        max_frames, max_bytes = _max_frames(), _max_bytes()
        while room.frames and (len(room.frames) > max_frames
                               or room.held_bytes > max_bytes):
            _gone_digest, gone = room.frames.popitem(last=False)
            room.held_bytes -= gone.nbytes
            room.evicted += 1
        return entry


def recall(key: tuple[str, str], digest: str) -> Shown | None:
    """Достать показанное по подписи. Промах — это НЕ ошибка витрины: так
    выглядит и устаревший кадр, и подпись, которой здесь не показывали."""
    if not digest:
        return None
    with _LOCK:
        room = _ROOMS.get(key)
        if room is None:
            return None
        entry = room.frames.get(digest)
        if entry is not None:
            room.frames.move_to_end(digest)
        return entry


def levels(key: tuple[str, str]) -> dict[str, str]:
    """этаж -> подпись самого свежего показанного кадра."""
    with _LOCK:
        room = _ROOMS.get(key)
        return dict(room.latest) if room is not None else {}


def forget(key: tuple[str, str] | None = None) -> None:
    """Забыть показанное сессии — И КАДРЫ, И ПОДПИСЬ.

    🔴 ДЕФЕКТ, НАЙДЕННЫЙ ЖИВЬЁМ 14.08.2026, И ОН СРАБОТАЛ У ВЛАДЕЛЬЦА.
    Витрина держит ДВА хранилища: `_ROOMS` (кадры) и `_SCENES` (накопленная
    подпись показанного). Эта функция чистила только первое. Значит сессия,
    которую «забыли», продолжала носить подпись прошлой сцены — и ворота
    переноса сверяли новую панель со СТАРОЙ подписью, отвечая
    `shown_mismatch` там, где сверять было нечего.

    Это и есть наш класс в чистом виде: величина живёт в двух местах, и ничто
    не заставляет их сходиться. Один прибор об этом говорил —
    `test_nothing_shown_is_its_own_refusal` краснел в общем прогоне и зеленел
    в одиночку, потому что зависел от того, кто наполнил `_SCENES` до него.
    Я прочитал этот красный как «чужой» и отложил; через час он вышел на
    экран владельца отказом с двумя шестидесятичетырёхзначными подписями.
    """
    with _LOCK:
        if key is None:
            _ROOMS.clear()
            _SCENES.clear()
        else:
            _ROOMS.pop(key, None)
            _SCENES.pop(key, None)


reset = forget


def stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "schema": SHOWROOM_SCHEMA,
            "sessions": len(_ROOMS),
            "frames": sum(len(r.frames) for r in _ROOMS.values()),
            "bytes": sum(r.held_bytes for r in _ROOMS.values()),
            "shown_total": sum(r.shown_total for r in _ROOMS.values()),
            "evicted": sum(r.evicted for r in _ROOMS.values()),
            "max_frames": _max_frames(),
            "max_bytes": _max_bytes(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# ПОДПИСЬ ПОКАЗАННОЙ СЦЕНЫ — накопленная, потому что сцена приезжает частями
# ═══════════════════════════════════════════════════════════════════════════
#
# ЗАЧЕМ ОТДЕЛЬНО ОТ `show`. `show` подписывает КАДР ПЛАНА: набор программ
# одного этажа, показанный один раз. Вьюер же с волны дельт показывает
# НАКОПЛЕННОЕ: целое здание приезжает базой, дальше — хвостами, и человек
# смотрит на их склейку. Кнопка «отправить в Revit» подписывает то, что человек
# видел, значит подписывать надо склейку, а не последний хвост.
#
# ПОЧЕМУ МУЛЬТИМНОЖЕСТВО, А НЕ ЦЕПОЧКА. Найдено проверкой ДО поставки
# (`verify_shown.mjs`): целая сцена перечисляет элементы в порядке «сначала все
# тела, потом все призраки», а склейка — «тела и призраки базы, затем тела и
# призраки хвоста». Здание ОДНО И ТО ЖЕ, порядок в буфере разный, и цепочка
# хешей объявила бы их разными. Порядок в буфере — деталь рисования, а не
# свойство здания, поэтому подпись обязана его не замечать.
#
# Сумма по модулю 2^256 от sha256 каждой записи даёт ровно это: она не зависит
# от порядка и остаётся O(нового) на кадр. Взято СУММИРОВАНИЕ, а не XOR:
# XOR гасит пары, то есть два одинаковых элемента исчезли бы бесследно, а
# продублированный дельтой элемент — ровно тот дефект, который подпись обязана
# ловить.
#
# ПОЧЕМУ ХЕШ НАКАПЛИВАЕТСЯ, А НЕ СЧИТАЕТСЯ ЗАНОВО. `hashlib` умеет `update`,
# поэтому сервер добавляет РОВНО записи новых элементов и остаётся O(нового) на
# кадр — то самое свойство, ради которого делались дельты. Пересчёт по всей
# сцене вернул бы кадру стоимость целого, то есть починил бы транспорт и
# сломал бы его же кнопкой.
#
# ПОЧЕМУ СЕРВЕР СЧИТАЕТ САМ, А НЕ БЕРЁТ У ПАНЕЛИ. Если продолжать цепочку от
# присланного значения, клиент со сломанной склейкой прислал бы своё
# неправильное «предыдущее», сервер продолжил бы от него, и подписи сошлись бы
# при разошедшихся зданиях. Две стороны обязаны считать НЕЗАВИСИМО: сервер —
# по тому, что отправил, панель — по тому, что нарисовала. Совпадение тогда
# означает совпадение, а не вежливость.

SCENE_SCHEMA = "kir-shown-scene/1"


#: Модуль суммы. 2^256 — ровно ширина sha256, поэтому сумма не теряет бит.
_SCENE_MOD = 1 << 256


@dataclass(slots=True)
class _Scene:
    """Накопленная подпись показанной сцены одной сессии."""

    total: int = 0
    elements: int = 0
    frames: int = 0
    records_bytes: int = 0

    def hexdigest(self) -> str:
        """Сумма -> те же 64 hex, что у sha256: потребителю знать о сумме
        незачем, а формат подписи в пакете один."""
        return format(self.total % _SCENE_MOD, "064x")


_SCENES: "OrderedDict[tuple[str, str], _Scene]" = OrderedDict()


def scene_reset(key: tuple[str, str]) -> str:
    """Начать подпись заново — целая сцена (`since=0`) обнуляет накопление.

    Возвращает подпись ПУСТОЙ сцены, а не пустую строку: «ничего не показано»
    — это состояние, у которого есть подпись, и отличать его от «сессии нет»
    обязано значение, а не его отсутствие.
    """
    with _LOCK:
        scene = _Scene()
        _SCENES[key] = scene
        _SCENES.move_to_end(key)
        while len(_SCENES) > _max_sessions():
            _SCENES.popitem(last=False)
        return scene.hexdigest()


def scene_shown(key: tuple[str, str], records: Sequence[bytes], *,
                elements: int, whole: bool) -> str:
    """Добавить показанное к подписи сессии и вернуть НАКОПЛЕННОЕ значение.

    `whole=True` (целая сцена) обнуляет накопление перед добавлением: база
    заменяет всё, что панель держала до неё. `whole=False` — хвост, он только
    дописывается.
    """
    if whole or key not in _SCENES:
        scene_reset(key)
    with _LOCK:
        scene = _SCENES.get(key)
        if scene is None:  # вытеснили между строками — начинаем заново
            scene = _Scene()
            _SCENES[key] = scene
        for record in records:
            scene.total = (scene.total + int.from_bytes(
                hashlib.sha256(record).digest(), "big")) % _SCENE_MOD
            scene.records_bytes += len(record)
        scene.elements += int(elements)
        scene.frames += 1
        _SCENES.move_to_end(key)
        return scene.hexdigest()


def scene_digest(key: tuple[str, str]) -> str:
    """Текущая подпись показанного сессии. Пустая строка — НЕ ПОКАЗЫВАЛИ.

    Пустая строка и подпись пустой сцены — разные факты, и путать их нельзя:
    первое значит «этой сессии сервер не показывал ничего», второе — «показал,
    и там было пусто».
    """
    with _LOCK:
        scene = _SCENES.get(key)
        return scene.hexdigest() if scene is not None else ""


def scene_stats(key: tuple[str, str]) -> dict[str, Any]:
    with _LOCK:
        scene = _SCENES.get(key)
        if scene is None:
            return {"shown": False}
        return {"shown": True, "schema": SCENE_SCHEMA,
                "digest": scene.hexdigest(),
                "elements": scene.elements, "frames": scene.frames,
                "records_bytes": scene.records_bytes}
