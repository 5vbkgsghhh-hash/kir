"""СЦЕНА ЗДАНИЯ ИЗ РАЗБОРА — оболочки `clash` плюс слой честности, в байты.

ЧТО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ, И ЭТО ГЛАВНОЕ. Он не строит геометрию. Вся
геометрия уже построена `clash/hulls.py` и `clash/snapshot.py`, и этот модуль
их только ЧИТАЕТ (в `clash` не написано ни строки — там работает другой агент).
Замер, ради которого стоило проверить перед постройкой: `build_from_decompile`
на `демо-v3` — 84 120 оболочек за 6.5–7.3 с; на `sob62_fas_r23_v19` — 4 218 за
0.39 с. Своего экстрактора геометрии вьюеру не нужно, и писать его было бы
седьмым графом ровно в том смысле, в каком о них говорит роадмап.

ПОЧЕМУ СЦЕНА БЕРЁТСЯ ИЗ ОБОЛОЧЕК, А НЕ ИЗ ТЕЛ. Тел нет. `hulls` строит
КОНСЕРВАТИВНЫЕ НАДМНОЖЕСТВА, и `grade="exact"` недостижим по выводу
(`hulls.UNREACHABLE_GRADE_REASONS`). Вьюер, рисующий оболочку и называющий её
телом, повторил бы дефект «зелёный свидетель непрочитанной оси» в графике.
Поэтому `Fidelity` едет с каждым элементом, и форма отрисовки выбирается по
ней, а не по категории.

ПЕРЕПИСЬ ЕДЕТ СО СЦЕНОЙ. `snapshot.Census` уже держит закон
`eligible = hulled + unsupported + missing_geometry`, и он сходится по
каждому разбору. Сцена публикует его целиком, потому что «здание выглядит
целым» и «здание целое» — разные утверждения: на `sob62_fas_r23_v19` из
5 001 пригодного элемента оболочку получили 4 218, а 783 (15.66 %) не
получили ничего и в сцене их НЕТ. Пользователь обязан видеть это число рядом
с картинкой, иначе картинка врёт умолчанием.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import time
from typing import Any

from kukai.viewer import graph as _graph
from kukai.viewer import honesty as _honesty
from kukai.viewer.codec import SceneBuilder

__all__ = ("TRUST_CODE", "FIDELITY_CODE", "scene_from_decompile", "run_root",
           "list_runs")

#: Числовые коды состояний в буфере. Порядок = порядок тревожности, и он же
#: порядок легенды во вьюере. Публикуется в заголовке сцены: клиент не должен
#: держать вторую копию этой таблицы.
TRUST_CODE: dict[str, int] = {
    _honesty.Trust.OP_PROVEN.value: 0,
    _honesty.Trust.OP_UNPROVEN.value: 1,
    _honesty.Trust.ATOM.value: 2,
    _honesty.Trust.UNKNOWN.value: 3,
}

FIDELITY_CODE: dict[str, int] = {
    _honesty.Fidelity.EXACT.value: 0,
    _honesty.Fidelity.SHAPED.value: 1,
    _honesty.Fidelity.BOX_ONLY.value: 2,
    _honesty.Fidelity.DEGENERATE.value: 3,
    _honesty.Fidelity.NO_BODY.value: 4,
}


def _graph_enabled() -> bool:
    """Флаг чужого модуля, спрошенный без его импорта в горячем пути."""
    try:
        from kukai.ir.decompile.building_graph import building_graph_enabled
        return building_graph_enabled()
    except Exception:  # noqa: BLE001 — модуль недоступен: слоя просто нет
        return False


#: Один центральный кран на корпус разборов вместо частных симлинков.
#: ЗАВЕДЁН ПО ЗАМЕРУ 11.08.2026: корпус (4.1 ГБ, 76 прогонов, 67 с `L0.jsonl`)
#: машинно-локален и лежит ТОЛЬКО у прода, а путь выводился из `__file__` —
#: значит в любом worktree он указывал в пустоту, и целое семейство тестов
#: либо падало `FileNotFoundError`, либо тихо получало пустой список. Первый
#: обошедший это сделал приватный симлинк внутрь своего дерева: зелень,
#: которая не воспроизводится ни у кого другого. Пять таких симлинков — это
#: один и тот же дефект, размноженный впятеро.
CORPUS_ENV = "KUKAI_DECOMPILE_CORPUS"


def run_root() -> pathlib.Path:
    """Корпус разборов. `backend` удвоен НЕ ПО ОШИБКЕ — так лежит на проде.

    Переопределяется ``KUKAI_DECOMPILE_CORPUS``: корпус машинно-локален, и
    из чужого worktree иначе недостижим.
    """
    override = os.environ.get(CORPUS_ENV, "").strip()
    if override:
        return pathlib.Path(override)
    here = pathlib.Path(__file__).resolve()
    # kukai/viewer/scene.py -> kukai -> backend
    backend = here.parent.parent.parent
    return backend / "backend" / "data" / "decompile"


def corpus_unreachable_reason() -> str | None:
    """``None``, если корпус на месте; иначе ПРИЧИНА словами.

    Закон, купленный сегодня дважды: ЛЮБОЙ НОЛЬ, СНЯТЫЙ С КОРПУСА, ОБЯЗАН
    ЕХАТЬ С ДОКАЗАТЕЛЬСТВОМ, ЧТО КОРПУС БЫЛ ДОСТИЖИМ. «Я посмотрел и не
    нашёл» и «этого нет» — одна фраза и разные факты; пустой список от
    отсутствующего каталога неотличим от честно пустого корпуса.
    """
    root = run_root()
    if root.is_dir():
        return None
    return (f"корпус разборов недостижим: {root} не существует — "
            f"задай {CORPUS_ENV} (у прода это "
            f"/opt/kukai-rebuild1/backend/backend/data/decompile)")


#: Имя здания из паспорта, ключ — (путь, mtime, размер). Паспорт переписывают
#: целиком, поэтому пара (mtime, размер) — достаточный признак изменения, а
#: путь один и тот же только у одного и того же разбора.
_DOC_NAME_CACHE: dict[tuple[str, int, int], str] = {}

_DOC_NAME_RE = re.compile(rb'"doc_name"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _doc_name_of(passport: pathlib.Path) -> str:
    """Имя здания из паспорта БЕЗ разбора паспорта целиком.

    🔴 ЗАМЕР 14.08.2026, найден по секундомеру в окне КИР: список корпуса
    отвечал **16.8 с** — 69 разборов, из них у 52 есть паспорт, и прежняя
    строка делала `json.loads(passport.read_text())` на каждом. Паспорта
    бывают по **196 МБ** (`k2_ar_rd_v7`), суммарно **918 МБ**, и всё это
    разбиралось в объекты ради ОДНОГО строкового поля. Панель молчала
    семнадцать секунд, а здание, названное в адресе, ждало этот список.

    Ищем ключ побайтно и останавливаемся на первом совпадении. Полный
    просмотр, а не «первые N КБ»: у 10-мегабайтного паспорта `doc_name`
    лежит в первых 400 КБ, у 196-мегабайтного — нет, и головной срез
    отвечал бы «имени нет» там, где оно есть. Пустая строка здесь означает
    «в паспорте такого поля нет», и это единственное, что она означает.
    """
    try:
        st = passport.stat()
    except OSError:
        return ""
    key = (str(passport), st.st_mtime_ns, st.st_size)
    hit = _DOC_NAME_CACHE.get(key)
    if hit is not None:
        return hit
    found = ""
    try:
        with passport.open("rb") as fh:
            tail = b""
            while True:
                chunk = fh.read(4 << 20)
                if not chunk:
                    break
                buf = tail + chunk
                m = _DOC_NAME_RE.search(buf)
                if m:
                    found = json.loads(b'"' + m.group(1) + b'"')
                    break
                # Хвост на стык: ключ может лечь на границу чтения.
                tail = buf[-256:]
    except Exception:  # noqa: BLE001 — паспорт не обязателен
        found = ""
    if len(_DOC_NAME_CACHE) > 512:
        _DOC_NAME_CACHE.clear()
    _DOC_NAME_CACHE[key] = found
    return found


def list_runs() -> list[dict[str, Any]]:
    """Разборы, у которых есть поток L0. Имя каталога НЕ ЕСТЬ имя здания:
    `snowdon_plumb_v5` содержит архитектурную модель (замер 10.08: 1 425
    импостов витража и 1 136 стен, ни одной трубы), поэтому рядом с каталогом
    публикуется `doc_name` из паспорта, когда он есть."""
    root = run_root()
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        l0 = entry / "L0.jsonl"
        if not entry.is_dir() or not l0.exists():
            continue
        # КОГДА РАЗОБРАНО — ЕДИНСТВЕННОЕ, ЧЕМ 69 РАЗБОРОВ ОТЛИЧАЮТСЯ ДЛЯ ТОГО,
        # КТО ВЫБИРАЕТ (14.08.2026). Владелец: «не могу нормально добавить
        # здание» — в списке 71 строка вида `k2_ar_rd_v13`, и по ним нельзя
        # понять ни что это, ни какое свежее. Время берётся у потока L0, а не
        # у каталога: каталог трогает любая служебная запись рядом, поток —
        # только сам разбор. Байты потока едут ЯВНО названными байтами, а не
        # переодетым «числом элементов»: числа элементов здесь нет, и
        # подсовывать вместо него размер значило бы соврать единицей.
        try:
            st = l0.stat()
            mtime, size = st.st_mtime, st.st_size
        except OSError:
            mtime, size = 0.0, 0
        out.append({"run": entry.name,
                    "doc_name": _doc_name_of(entry / "passport.json"),
                    "l0_mtime": round(mtime, 3),
                    "l0_bytes": size,
                    "has_tree": (entry / "tree.json").exists()})
    return out


def scene_from_decompile(run: str) -> tuple[bytes, dict[str, Any]]:
    """Разбор -> байты сцены + справка. Единственный вход для «открыть модель».

    Ленивые импорты `clash` намеренно: вьюер обязан подниматься и тогда, когда
    в `clash` идёт правка (там сейчас работает другой агент), а не падать на
    импорте модуля целиком.
    """
    from kukai.clash import geom as G
    from kukai.clash import hulls as H
    from kukai.clash import snapshot as S

    root = run_root() / run
    if not root.exists():
        raise FileNotFoundError(f"разбора {run!r} нет в {run_root()}")

    t0 = time.perf_counter()
    snap = S.build_from_decompile(root)
    t_hulls = time.perf_counter() - t0

    t1 = time.perf_counter()
    l1, l1_note = _honesty.read_l1_honesty(root)
    t_l1 = time.perf_counter() - t1

    # ── СЛОЙ ГРАФА. Строится из ТОГО ЖЕ L0, что и оболочки, и из тех же
    #    атомов L1: `generator_child` — единственный свидетель выведенности,
    #    какой сегодня есть в данных, и он подаётся ЯВНО. Уважает флаг чужого
    #    модуля; выключенный флаг даёт `available: false` с причиной, а не
    #    молчание.
    t3 = time.perf_counter()
    graph_facts: dict[str, _graph.ElementGraph] = {}
    graph_note = _graph.unavailable(
        "KUKAI_IR_BUILDING_GRAPH не задан: граф здания не строился. Его "
        "владелец держит модуль за флагом, пока тот не сверен с живым Revit, "
        "и показывать непроверенное как правду вьюер не вправе")
    # ФЛАГ СПРАШИВАЕТСЯ ДО ЧТЕНИЯ, А НЕ ПОСЛЕ. Граф требует ВТОРОГО прохода
    # по L0 (`build_from_decompile` строки внутрь не отдаёт), и это самая
    # дорогая часть слоя: замер 11.08 — 0.25 с на фасаде и ~3.2 с на демо-v3.
    # Платить её при выключенном флаге значило бы брать деньги за товар,
    # который заведомо не выдаётся.
    if _graph_enabled():
        kids = [sid for sid, (trust, why) in l1.items()
                if trust is _honesty.Trust.ATOM and why == "generator_child"]
        try:
            elements, _profiles, _curves, l0_origin = S.read_decompile(root)
            graph_facts, graph_note = _graph.facts_for_decompile(
                l0_origin, elements, generator_child_ids=kids,
                l1_source_ids=list(l1))
        except Exception as exc:  # noqa: BLE001 — слой графа не роняет картинку
            graph_facts, graph_note = {}, _graph.unavailable(
                f"L0 не перечитался для графа: {type(exc).__name__}")
    t_graph = time.perf_counter() - t3

    # ОБЩЕЕ НАЧАЛО — не косметика: float32 точен на целых до 16.7 млн мм, и
    # площадка в геодезических координатах съедает этот запас расстоянием до
    # начала координат, а не размером здания (см. шапку `codec`).
    t2 = time.perf_counter()
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for rec in snap.records:
        a, b = rec.bounds()
        for i in range(3):
            lo[i] = min(lo[i], a[i])
            hi[i] = max(hi[i], b[i])
    if not snap.records:
        lo, hi = [0.0] * 3, [0.0] * 3
    origin = ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, lo[2])

    builder = SceneBuilder(origin_mm=origin)
    census = _honesty.HonestyCensus()
    axes_tally: dict[int, int] = {}
    #: Память по ИМЕНИ ОПА. Оси зависят только от имени, поэтому кэш — не
    #: оптимизация «на всякий случай», а следствие формы правила: на демо-v3
    #: это 84 120 элементов на 30 различных имён. Словарь ЛОКАЛЬНЫЙ: править
    #: чужой модуль ради скорости значило бы менять поведение всем.
    axes_cache: dict[str, int] = {}

    def axes_for(op_name: str, judgeable: bool) -> int:
        if not judgeable:
            return _honesty.AXES_UNJUDGEABLE
        if op_name not in axes_cache:
            axes_cache[op_name] = _honesty.axes_byte(
                _honesty.axes_for_ops([op_name]))
        return axes_cache[op_name]

    for rec in snap.records:
        hull = rec.hull
        if isinstance(hull, G.Capsule):
            kind, slot = builder.add_capsule(hull.path, hull.radius)
        elif isinstance(hull, G.PrismSet):
            kind, slot = builder.add_prism(hull.pieces, hull.z0, hull.z1)
        elif isinstance(hull, G.Prism):
            kind, slot = builder.add_prism((hull.footprint,), hull.z0, hull.z1)
        else:
            a, b = rec.bounds()
            kind, slot = builder.add_box(a, b)

        trust, why = l1.get(rec.source_id,
                            (_honesty.Trust.UNKNOWN, ""))
        fidelity = _honesty.fidelity_of(
            rec.grade, rec.hull_source, H.hull_degeneracy(hull))
        item = _honesty.ElementHonesty(
            element_id=rec.source_id, trust=trust, fidelity=fidelity, why=why,
            benign=(trust is _honesty.Trust.ATOM
                    and why in _honesty.BENIGN_ATOM_REASONS))
        census.add(item)
        # ОСИ ДЛЯ РАЗОБРАННОГО ЗДАНИЯ ЧИТАЮТСЯ ИНАЧЕ, ЧЕМ ДЛЯ ЖИВОГО, и это
        # не педантизм. Элемент разбора НЕ СТРОИЛСЯ этим опом — он им ПОДНЯТ.
        # Поэтому утверждение здесь ровно такое: «пересборка этого элемента
        # опом X оставила бы эти оси без свидетеля», а не «оси этого элемента
        # не проверяли». Формулировка едет на экран полем `axes_ru`, чтобы
        # разница не потерялась между сервером и картинкой.
        axes = axes_for(why, trust in (_honesty.Trust.OP_PROVEN,
                                       _honesty.Trust.OP_UNPROVEN))
        axes_tally[axes] = axes_tally.get(axes, 0) + 1
        # Оболочка без узла графа получает `unknown`, а НЕ `materialized`:
        # «граф про этот элемент молчит» и «элемент построен» — разные факты.
        node = graph_facts.get(rec.source_id)
        builder.add_element(
            element_id=rec.source_id, category=rec.category,
            level=rec.level_id, trust=TRUST_CODE[trust.value],
            fidelity=FIDELITY_CODE[fidelity.value], kind=kind, slot=slot,
            label=rec.type_name or "", axes=axes,
            authority=_graph.AUTHORITY_CODE.get(
                node.authority if node else "unknown", 2),
            existence=_graph.EXISTENCE_CODE.get(
                node.existence if node else "unknown", 2),
            flags=node.flags if node else 0)
    t_pack = time.perf_counter() - t2

    meta: dict[str, Any] = {
        "run": run,
        "source": "model",
        # ЧЕСТНОСТЬ ИСТОЧНИКА, тем же словарём, что в `preview`: это
        # НЕЗАВИСИМОЕ ЧТЕНИЕ документа, а не пересказ программы.
        "assertion": "independent",
        "assertion_ru": "НЕЗАВИСИМОЕ чтение модели (разбор), не заявление программы",
        "trust_codes": TRUST_CODE,
        "fidelity_codes": FIDELITY_CODE,
        "honesty": census.to_dict(),
        "honesty_source": l1_note,
        "census": snap.census.as_dict(),
        "join_manifest": snap.join_manifest(),
        "by_grade": snap.by_grade(),
        # ЭЛЕМЕНТЫ, КОТОРЫХ В СЦЕНЕ НЕТ. Без этой строки картинка врёт
        # умолчанием: на фасаде это 783 из 5 001 (15.66 %).
        "not_in_scene": snap.join_manifest()["not_scored"],
        "graph": graph_note,
        "authority_codes": _graph.AUTHORITY_CODE,
        "existence_codes": _graph.EXISTENCE_CODE,
        "flag_bits": {"refuted": _graph.FLAG_REFUTED,
                      "unresolved": _graph.FLAG_UNRESOLVED},
        "flags_ru": {"refuted": "у элемента ОПРОВЕРГНУТО отношение — назван "
                                "правилом, снявшим ребро (сам элемент цел)",
                     "unresolved": "у элемента есть отношение, чья ЦЕЛЬ вне "
                                   "извлечения: проверить нечем"},
        "timing_ms": {"hulls": round(t_hulls * 1000, 1),
                      "l1": round(t_l1 * 1000, 1),
                      "graph": round(t_graph * 1000, 1),
                      "pack": round(t_pack * 1000, 1)},
        # СВЕРКА С ПЛАНОМ НЕ ВХОДИТ В СЦЕНУ, И ЭТО СКАЗАНО. План и объём
        # показывают РАЗНОЕ (замер 11.08: 337 элементов только на плане, 270
        # только в объёме, 663 ни там ни там — фасад), и молчание сцены об
        # этом читается как «расхождений нет».
        "reconcile": {"available": False,
                      "reason": ("сверка с планом не запрашивалась: она строит "
                                 "обе переписи целиком и стоит их суммы"),
                      "endpoint": "/api/viewer/reconcile"},
        # ПРЕДЛОЖЕНИЯ РАЗВЕДЕНИЯ В СЦЕНУ НЕ ВХОДЯТ, И ЭТО СКАЗАНО. Замер
        # 11.08: одна пара стоит 29.1 мс (фасад) и 372.4 мс (инженерия), а
        # перекрытий 19 239 и 35 633 — то есть 9.3 минуты и 3.7 часа на
        # здание. Молчание сцены читалось бы как «разводить нечего».
        "advice": {"available": False,
                   "reason": ("предложения разведения не запрашивались: одна "
                              "пара стоит 29–372 мс, полное здание — часы"),
                   "endpoint": "/api/viewer/advice"},
        "blind_spots": BLIND_SPOTS,
        "axes_order": list(_honesty.AXES_ORDER),
        "axes_unjudgeable": _honesty.AXES_UNJUDGEABLE,
        "axes_tally": {str(k): v for k, v in sorted(axes_tally.items())},
        "axes_ru": ("оси, по которым обязательств НЕ ОБЪЯВЛЕНО: пересборка "
                    "этого элемента его опом оставила бы их без свидетеля"),
    }
    blob = builder.finish(meta)
    meta["bytes"] = len(blob)
    return blob, meta


#: ЧЕГО ЭТА СЦЕНА НЕ ПОКАЗЫВАЕТ. Печатается в самом вьюере, а не прячется в
#: документации: молчание картинки читается как «всё в порядке» — ровно тот же
#: довод, по которому `preview.BLIND_SPOTS` печатается на листе плана.
BLIND_SPOTS: tuple[str, ...] = (
    "НЕ ТЕЛА, А ОБОЛОЧКИ: каждая содержит элемент и почти всегда больше него; "
    "grade=exact недостижим по выводу, так что ни одна форма здесь не равна "
    "настоящей",
    "габарит — не форма: на демо-v3 99.89 % элементов известны только "
    "габаритным боксом, и они нарисованы боксами намеренно",
    "то, что выводит Revit (стыковки стен, составные слои, триангуляция "
    "рельефа, фитинги трасс), офлайн не считается и здесь отсутствует",
    "элементы связанных файлов оболочек не получают — межразделная картина "
    "пуста не потому, что чисто",
    "клеши: пересечения тел здесь не ищутся и не показываются",
    "материалы, слои конструкции и внешний вид — цвет здесь означает доверие, "
    "а не материал",
)
