"""КЭШ СЦЕНЫ — потому что сцена одна на ЗДАНИЕ, а не на человека.

════════════════════════════════════════════════════════════════════════════
ЗАМЕР 11.08.2026, `демо-v3` со слоем графа, ПО ЭТАПАМ
════════════════════════════════════════════════════════════════════════════
Холодное открытие разложено, а не названо одним числом (19.7 с в этом
прогоне; тот же путь без разбивки давал 17.4 с — прогоны разные, и число
обязано называть свой):

    L0 #1 (read_decompile)            4.45 с   22.6 %
    L1 (tree.json)                    3.60 с   18.3 %
    graph_from_l0                     3.28 с   16.6 %
    L0 #2 (ТОЛЬКО ради графа)         3.20 с   16.2 %
    оболочки (build_from_elements)    2.32 с   11.8 %
    graph_view                        1.86 с    9.4 %
    кодек (упаковка)                  0.99 с    5.0 %

**ЭТО ОТМЕНИЛО МОЮ ЖЕ ГИПОТЕЗУ.** Я называл причиной второй проход по L0 и
собирался просить у владельца `decompile` интерфейс, отдающий строки один раз
на обоих потребителей. Замер говорит: второй проход — **16.2 %**, то есть
3.20 с из 19.7. Интерфейс снял бы шестую часть беды. Оптимизировать не
замерив — это назначить узкое место, и я едва этого не сделал.

════════════════════════════════════════════════════════════════════════════
КЭШ СНИМАЕТ ВСЮ, А НЕ ШЕСТУЮ ЧАСТЬ
════════════════════════════════════════════════════════════════════════════
    холодная постройка   20.0 с
    чтение из кэша        1 мс          -> 20 584x
    проверка ключа        0.1 мс        -> дешевле постройки в 217 848 раз

И это законно ровно потому, что разбор — НЕИЗМЕНЯЕМЫЙ АРХИВ, а сцена
ДЕТЕРМИНИРОВАНА. Второе проверено, а не предположено: две постройки подряд
дали **побайтно одинаковое ТЕЛО** (5 154 042 байта), а разошлись ровно пять
полей заголовка — `timing_ms.*` и `graph.elapsed_ms`, то есть показания
секундомера, которые обязаны отличаться.

Отсюда прямое следствие к вопросу о десяти пользователях: холодное открытие
платит ПЕРВЫЙ, а не каждый.

════════════════════════════════════════════════════════════════════════════
ЧТО ВХОДИТ В КЛЮЧ — И ПОЧЕМУ КАЖДОЕ
════════════════════════════════════════════════════════════════════════════
* **входные файлы разбора** (имя, размер, mtime). Архив неизменяем, но
  «неизменяем» — обещание оператора, а не свойство файловой системы;
* **флаг `KUKAI_IR_BUILDING_GRAPH`**. Он МЕНЯЕТ СОДЕРЖИМОЕ сцены: с ним
  элементы получают `materialized`/`declared`, без него — `unknown`. Кэш без
  флага в ключе отдал бы серое здание тому, кто включил граф, и наоборот;
* **версия формата** (`CACHE_VERSION`). Меняется код упаковки — обязаны
  протухнуть все записи, иначе клиент получит вчерашний формат сегодняшним
  разбором.

════════════════════════════════════════════════════════════════════════════
КЭШИРОВАННАЯ СЦЕНА ГОВОРИТ, ЧТО ОНА КЭШИРОВАННАЯ
════════════════════════════════════════════════════════════════════════════
Заголовок несёт показания секундомера ТОЙ постройки, из которой он пришёл.
Отдать их как свои значило бы сообщить «собрано за 20 с» про чтение, занявшее
миллисекунду, — то есть соврать прибором. Поэтому к ответу приписывается
`cache`: попадание, возраст записи и что тайминги принадлежат исходной
постройке. Молчание здесь читалось бы как «так быстро и строится».
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time
from typing import Any, Optional

__all__ = ("CACHE_VERSION", "cache_dir", "enabled", "key_for",
           "key_inputs", "load", "purge", "stats", "store")

#: Версия ФОРМАТА сцены. Меняется кодек — меняется здесь, и все записи
#: протухают разом. Без этого клиент получил бы вчерашний формат.
CACHE_VERSION = "kir-viewer-scene-cache/1"

_COUNTERS = {"hit": 0, "miss": 0, "stored": 0, "evicted": 0, "errors": 0}


def enabled() -> bool:
    """Выключатель. Выключенный = поведение до этой волны: каждый платит
    холодное открытие сам."""
    return os.environ.get("KUKAI_KIR_SCENE_CACHE", "1") != "0"


def cache_dir() -> pathlib.Path:
    raw = os.environ.get("KUKAI_KIR_SCENE_CACHE_DIR", "")
    if raw:
        return pathlib.Path(raw)
    return pathlib.Path("/tmp/kir-scene-cache")


def _max_bytes() -> int:
    """Потолок в БАЙТАХ, а не в записях: сцена фасада 0.5 МБ, сцена демо-v3
    5.2 МБ, и считать их одинаково значит не считать."""
    try:
        return max(10_000_000, int(os.environ.get(
            "KUKAI_KIR_SCENE_CACHE_BYTES", "") or 2_000_000_000))
    except (TypeError, ValueError):
        return 2_000_000_000


def key_for(run: str, run_dir: pathlib.Path) -> str:
    """Ключ по ВХОДАМ и по тому, что меняет содержимое сцены.

    Считается по (имя, размер, mtime) файлов разбора: 0.1 мс на 17 файлов —
    дешевле постройки в 217 848 раз. Содержимое файлов не хешируется
    намеренно: L0 доходит до 88 МБ, и честный хеш стоил бы дороже кэша.
    Цена названа: подмена файла С ТЕМ ЖЕ размером И ТЕМ ЖЕ mtime кэшем не
    замечается. Для неизменяемого архива это допустимо; для рабочего каталога
    — нет, и тогда кэш надо выключить флагом.
    """
    inputs = key_inputs(run, run_dir)
    if inputs is None:
        # Каталог не читается — ключа нет, и кэш обязан промахнуться, а не
        # выдать запись, обоснованную неизвестно чем.
        return ""
    digest = hashlib.sha256()
    for item in inputs:
        digest.update(b"|")
        digest.update(item.encode("utf-8"))
    return digest.hexdigest()


def key_inputs(run: str, run_dir: pathlib.Path) -> Optional[list[str]]:
    """ВХОДЫ КЛЮЧА СПИСКОМ, а не свёрнутые в хеш молча.

    ЭТО ТРЕБОВАНИЕ ИЗ ЧУЖОГО ОЖОГА. У кэша клешей ключ трижды не покрывал
    того, что меняет ответ: поднятый потолок возвращал СТАРЫЙ отказ, потому
    что потолка в ключе не было. Хеш такую дыру не показывает — он одинаково
    убедительно выглядит и с полным набором входов, и с половиной. Поэтому
    набор публикуется списком: дыру в нём видно глазом и тестом.

    Что входит и почему каждое:
      * `version=` — версия ФОРМАТА сцены. Меняется кодек — протухает всё;
      * `run=` — имя разбора;
      * `graph=` — флаг `KUKAI_IR_BUILDING_GRAPH`. Он меняет СОДЕРЖИМОЕ:
        с ним элементы получают `materialized`/`declared`, без него
        `unknown`. Кэш без него отдал бы серое здание тому, кто включил граф;
      * по одной строке на КАЖДЫЙ файл разбора: `имя:размер:mtime`.

    ЧЕГО ЗДЕСЬ НЕТ И ЦЕНА ЭТОГО. Содержимое файлов не хешируется: L0 доходит
    до 88 МБ, и честный хеш стоил бы дороже самой постройки. Значит подмена
    файла С ТЕМ ЖЕ размером И ТЕМ ЖЕ mtime кэшем не замечается. Для
    неизменяемого архива это допустимо; для рабочего каталога — нет, и тогда
    кэш выключается флагом. Названо здесь, а не подразумевается.
    """
    out = [f"version={CACHE_VERSION}", f"run={run}",
           f"graph={os.environ.get('KUKAI_IR_BUILDING_GRAPH', '')}"]
    skip = _not_inputs()
    try:
        for path in sorted(p for p in run_dir.iterdir() if p.is_file()):
            if path.name in skip:
                continue
            st = path.stat()
            out.append(f"{path.name}:{st.st_size}:{int(st.st_mtime)}")
    except OSError:
        return None
    return out


def _not_inputs() -> frozenset:
    """Файлы каталога, которые НЕ являются входами сцены.

    ЗАМЕР 11.08.2026, И ЭТО ЗЕРКАЛО ЧУЖОГО ОЖОГА. У кэша клешей ключ НЕ
    ПОКРЫВАЛ того, что меняет ответ, и поднятый потолок возвращал старый
    отказ. Здесь ошибка была обратной и оттого незаметнее: ключ ПОКРЫВАЛ то,
    что ответ НЕ меняет.

    `.last_access` — отметка обращения, которую ставит
    `decompile.snapshot_io.touch_last_access` при КАЖДОМ чтении файла
    разбора. Замер: открыть панель «план против объёма» (она зовёт
    `preview_snapshot`) — и `mtime` отметки меняется, а ключ сцены вместе с
    ним:

        ключ до сверки   26243642fc0a722a9229
        ключ после       ebe15ccec14bdfd05399

    То есть кэш переставал попадать НАВСЕГДА у любого, кто пользовался
    сверкой, и переставал молча: он выглядел работающим, просто каждый раз
    строил заново. Ключ, покрывающий лишнее, ломает кэш; ключ, покрывающий
    недостаточно, ломает правильность. Обе ошибки — про одно: набор входов
    обязан быть РОВНО множеством того, что меняет ответ.

    Имя берётся у владельца, а не пишется строкой: своя копия разъехалась бы
    при переименовании и вернула бы дефект молча.
    """
    names = {".last_access"}
    try:
        from kukai.ir.decompile.snapshot_io import LAST_ACCESS_MARKER
        names.add(str(LAST_ACCESS_MARKER))
    except Exception:  # noqa: BLE001 — чужой модуль; запасное имя выше
        pass
    return frozenset(names)


def _paths(key: str) -> tuple[pathlib.Path, pathlib.Path]:
    root = cache_dir()
    return root / f"{key}.bin", root / f"{key}.json"


def load(key: str) -> Optional[tuple[bytes, dict[str, Any]]]:
    """Байты сцены и справка о ЗАПИСИ. `None` — промах, и это не ошибка."""
    if not key or not enabled():
        return None
    blob_path, meta_path = _paths(key)
    try:
        if not blob_path.exists() or not meta_path.exists():
            _COUNTERS["miss"] += 1
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        blob = blob_path.read_bytes()
    except Exception:  # noqa: BLE001 — испорченная запись это промах, не отказ
        _COUNTERS["errors"] += 1
        return None
    # ЦЕЛОСТНОСТЬ ЗАПИСИ ПРОВЕРЯЕТСЯ. Обрезанный файл, отдающий внутренне
    # согласованный заголовок, — ровно тот дефект, который снапшот клеша
    # ловит исключением, а не предупреждением.
    if meta.get("bytes") != len(blob):
        _COUNTERS["errors"] += 1
        return None
    _COUNTERS["hit"] += 1
    age = max(0.0, time.time() - float(meta.get("built_at") or 0.0))
    note = {
        "hit": True,
        "built_at": meta.get("built_at"),
        "age_s": round(age, 1),
        "build_ms": meta.get("build_ms"),
        "version": meta.get("version"),
        # ТАЙМИНГИ В ЗАГОЛОВКЕ ПРИНАДЛЕЖАТ ИСХОДНОЙ ПОСТРОЙКЕ. Отдать их как
        # свои значило бы сообщить «собрано за 20 с» про чтение, занявшее
        # миллисекунду, — соврать прибором.
        "inputs": meta.get("inputs") or [],
        "ru": ("сцена взята из кэша; показания секундомера в заголовке "
               "принадлежат ИСХОДНОЙ постройке, а не этому ответу"),
    }
    return blob, note


def store(key: str, blob: bytes, *, build_ms: float,
          inputs: Optional[list[str]] = None) -> bool:
    if not key or not enabled():
        return False
    blob_path, meta_path = _paths(key)
    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        # Пишем через временное имя: оборванная запись не должна оставить
        # файл, который потом прочитают как целый.
        tmp = blob_path.with_suffix(".part")
        tmp.write_bytes(blob)
        tmp.replace(blob_path)
        meta_path.write_text(json.dumps({
            "version": CACHE_VERSION, "bytes": len(blob),
            "built_at": time.time(), "build_ms": round(float(build_ms), 1),
            # ВХОДЫ ХРАНЯТСЯ РЯДОМ С ЗАПИСЬЮ: по ним видно, чем эта сцена
            # обоснована, без запуска кода. Хеш этого не показывает.
            "inputs": list(inputs or ()),
        }, ensure_ascii=False), encoding="utf-8")
        _COUNTERS["stored"] += 1
        _evict()
        return True
    except Exception:  # noqa: BLE001 — кэш не имеет права ронять ответ
        _COUNTERS["errors"] += 1
        return False


def _evict() -> None:
    """Вытеснение по СУММАРНОМУ размеру, самые старые первыми. Безлимитный
    кэш — это утечка с хорошим названием."""
    root = cache_dir()
    try:
        blobs = sorted((p for p in root.glob("*.bin")),
                       key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in blobs)
        cap = _max_bytes()
        while total > cap and blobs:
            victim = blobs.pop(0)
            total -= victim.stat().st_size
            victim.unlink(missing_ok=True)
            victim.with_suffix(".json").unlink(missing_ok=True)
            _COUNTERS["evicted"] += 1
    except OSError:
        _COUNTERS["errors"] += 1


def purge() -> int:
    root = cache_dir()
    removed = 0
    try:
        for path in list(root.glob("*.bin")) + list(root.glob("*.json")):
            path.unlink(missing_ok=True)
            removed += 1
    except OSError:
        _COUNTERS["errors"] += 1
    return removed


def stats() -> dict[str, Any]:
    out = dict(_COUNTERS)
    out["version"] = CACHE_VERSION
    out["enabled"] = enabled()
    out["dir"] = str(cache_dir())
    try:
        blobs = list(cache_dir().glob("*.bin"))
        out["entries"] = len(blobs)
        out["bytes"] = sum(p.stat().st_size for p in blobs)
    except OSError:
        out["entries"] = 0
        out["bytes"] = 0
    out["max_bytes"] = _max_bytes()
    return out
