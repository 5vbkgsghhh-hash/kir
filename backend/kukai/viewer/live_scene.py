"""СЦЕНА ИЗ ЖИВОГО ЖУРНАЛА — то, что модель ЗАЯВИЛА, ещё не построив.

ЭТО ТА ПОЛОВИНА, РАДИ КОТОРОЙ ВСЁ. `scene.py` показывает РАЗОБРАННОЕ здание.
Здесь — то, чего в Revit ещё нет вовсе: программы трёхчасовой сессии из
`kukai.live.journal`, включая незакоммиченное.

════════════════════════════════════════════════════════════════════════════
ТЕЛО СТРОИТ `clash_bundle`, А НЕ ЭТОТ МОДУЛЬ
════════════════════════════════════════════════════════════════════════════
`clash_bundle.bundle_elements(pack, snapshot=…)` уже превращает пачку программ
в элементы формы L0 — из СОБСТВЕННЫХ чисел программы и геометрии ТИПА,
разрешённого стадией ground против живого документа. Дальше они идут в тот же
`clash.snapshot.build_from_elements`, что и разобранное здание, то есть

    ЖИВАЯ СЦЕНА И СЦЕНА РАЗБОРА ПРОХОДЯТ ОДИН И ТОТ ЖЕ ГЕОМЕТРИЧЕСКИЙ ТРАКТ.

Это не экономия строк. Два тракта означали бы, что «я вижу стену в чате» и
«я вижу ту же стену, открыв модель» — два разных утверждения о геометрии, и
разошлись бы они молча.

════════════════════════════════════════════════════════════════════════════
ГЛАВНЫЙ ЗАМЕР: БЕЗ СНИМКА ОТКРЫТОЙ МОДЕЛИ ТЕЛ НЕТ ВООБЩЕ
════════════════════════════════════════════════════════════════════════════
11.08.2026, пачка из шести стен и трубы, `bundle_elements` + `build_from_elements`:

    без снимка   →  0 тел из 7,  все семь: `needs_live_model`
    (толщина стены и наружный диаметр трубы живут в ТИПЕ)

То же на масштабе (замер лида, `snowdon_plumb_v4`, дверь пересборки):

    без снимка   →     905 тел
    со снимком   →  16 247 из 16 257  (99.94 %)

Отсюда продуктовый вывод, который вьюер обязан показывать, а не скрывать:
**покрытие телами решает НЕ проводка, а наличие снимка открытой модели.**
Он приезжает в журнал через `plan_stream.remember_sections` и лежит в
`SessionJournal.sections`. Сессия без снимка — это сессия, где здание видно
контурами плана и НЕ видно телами, и сказать это надо словами.

════════════════════════════════════════════════════════════════════════════
ПОЧЕМУ У ЭЛЕМЕНТА НЕТ ТЕЛА — ПЯТЬ РАЗНЫХ ФАКТОВ, И ЧИНЯТ ИХ РАЗНЫЕ ЛЮДИ
════════════════════════════════════════════════════════════════════════════
`clash_bundle.BLIND_CLASS_RU` — закрытая таблица из пяти классов
(`never_a_body`, `op_expresses_no_body`, `not_declared_by_program`,
`needs_live_model`, `refused_by_hull_gate`) плюс `unclassified` для дыр в ней.
«Нет тела» без причины бесполезно; с причиной это указание, что делать:
операнд правит АВТОР, снимок — стадия ground, замок содержания — `kukai/clash`.

ЧЕСТНАЯ ГРАНИЦА ЭТОГО ПОКАЗА, И ОНА НАЗВАНА. `BundleGeometry.no_geometry`
считает причины ПАЧКОЙ (`{причина: сколько}`), а не поимённо по элементам.
Значит класс показывается РАСПРЕДЕЛЕНИЕМ по сессии, а на элементе — только
факт «тела нет» и отказ, который назвал сам построитель оболочек. Приписать
конкретному элементу конкретный класс было бы догадкой, а догадка, надетая на
элемент, читается как измерение.

════════════════════════════════════════════════════════════════════════════
КОНТУР ПЛАНА — ЗАПАСНОЙ ПУТЬ, И ОН ПОМЕЧЕН
════════════════════════════════════════════════════════════════════════════
Элемент без тела не имеет права ИСЧЕЗНУТЬ: пропавший неотличим от
несуществующего. Поэтому там, где `preview` знает контур в плане, элемент
рисуется экструзией этого контура и получает `Fidelity.NO_BODY` — то есть
на экране он призрак, а не тело. Высота, которой в программе нет, даёт
`FALLBACK_HEIGHT_MM` и метку `height_unknown`: правдоподобное число хуже
отсутствующего.

ИДЕНТИФИКАТОРЫ КВАЛИФИЦИРУЮТСЯ ЗАРАНЕЕ. `bundle_elements` адресует элементы
как `p1/w0` (`bundle_oid`), а `preview` — сырым `id` операции. Чтобы оба
говорили об одном элементе, пачка переписывается ОДИН раз перед обоими
вызовами: `id` и все ссылки `{"by":"ref"}` получают префикс программы.
Переписывание ТОТАЛЬНО и потому безопасно: `ref` по правилу компилятора
(`KIR-L003`) указывает только на более ранний оп ТОЙ ЖЕ программы, значит
ссылок наружу не бывает и разорвать нечего.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Mapping, Sequence

from kukai.viewer import graph as _graph
from kukai.viewer import honesty as _honesty
from kukai.viewer import reconcile as _reconcile
from kukai.viewer.codec import SceneBuilder
from kukai.viewer.scene import FIDELITY_CODE, TRUST_CODE

__all__ = ("FALLBACK_HEIGHT_MM", "FLOAT32_EXACT_MM", "LIVE_BLIND_SPOTS",
           "StaleBase", "base_digest", "programs_since",
           "scene_from_programs", "scene_from_session")

#: Радиус, в котором float32 представляет ЦЕЛЫЕ миллиметры точно: 24 бита
#: мантиссы = 16 777 216. Дальше от начала координат миллиметр перестаёт
#: быть представимым, и склейка дельты с базой поехала бы СУБМИЛЛИМЕТРОВО —
#: то есть незаметно. Поэтому радиус проверяется и называется, а не
#: подразумевается.
FLOAT32_EXACT_MM = 16_777_216.0


class StaleBase(ValueError):
    """База клиента не та, к которой применима дельта.

    ТИПИЗИРОВАННЫЙ ОТКАЗ, А НЕ ТИХАЯ СКЛЕЙКА. Приклеить хвост к чужой базе
    значит показать здание, которого никогда не существовало, — это хуже
    пустого экрана, потому что пустой экран виден.
    """

#: Высота, которой в программе НЕТ. Значение выбрано ЗАМЕТНЫМ, а не типовым:
#: 2500 мм похоже на настоящую стену и спряталось бы среди настоящих, а 100 мм
#: видно сразу. Элемент дополнительно помечается `height_unknown` и уезжает в
#: перепись — число здесь не «разумное умолчание», а признание незнания.
FALLBACK_HEIGHT_MM = 100.0

#: Имена параметров высоты по реестру. Список закрыт: параметра, которого здесь
#: нет, экструзия не увидит, и это уйдёт в `height_unknown`, а не в тихий ноль.
_HEIGHT_FIELDS = ("height_mm", "depth_mm", "thickness_mm")
_BASE_FIELDS = ("base_offset_mm", "offset_mm", "elev_mm")

LIVE_BLIND_SPOTS: tuple[str, ...] = (
    "это ЗАЯВЛЕНО программой, а не прочитано из Revit: модель ещё не строилась",
    "тела строит clash_bundle из чисел программы и типа; без снимка открытой "
    "модели тел нет вовсе — замер: 0 из 7 на пачке стен и трубы",
    "класс причины «нет тела» считается ПАЧКОЙ, а не на элементе: на элементе "
    "сказано только «тела нет» и отказ построителя оболочек",
    "высота берётся из параметра операции; где параметра нет — заглушка и "
    "метка height_unknown, а не правдоподобное число",
    "top_level не разрешается: это грундинг, а он требует живого документа",
    "всё, что выводит Revit (стыковки стен, слои, фитинги трасс, "
    "триангуляция рельефа), здесь отсутствует по построению",
    "часть программ Revit ещё отвергнет: журнал наполняется ДО записи",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def live_origin(datums: Sequence[Mapping[str, Any]]) -> tuple[float, float, float]:
    """Начало координат живой сцены — из ДАТУМОВ, а не из габарита элементов.

    ПОЧЕМУ ЭТО НЕСУЩЕЕ, А НЕ ВКУСОВОЕ. Кодек пишет координаты СМЕЩЕНИЯМИ от
    начала. Если начало считать по габариту текущих элементов (как делает
    сцена разбора), то каждая новая программа СДВИГАЕТ начало — и все ранее
    отправленные координаты становятся неверными. Дельта к такой базе
    склеивала бы здание из двух систем координат, причём расхождение росло бы
    плавно и потому невидимо.

    Отсюда правило: начало живой сцены зависит ТОЛЬКО от того, что дельта не
    меняет, — от датумов. `create_level` даёт отметку, XY остаётся нулевым:
    программу пишет автор, и её числа лежат у начала проекта по построению.

    ЦЕНА НАЗВАНА. Смещение теряет центрирование, поэтому здание дальше
    `FLOAT32_EXACT_MM` от начала проекта потеряет точность миллиметра. Это
    проверяется на каждой сцене (`origin_overflow`), а не обещается.
    """
    elevations = [float(op.get("elev_mm"))
                  for op in datums
                  if op.get("op") == "create_level"
                  and isinstance(op.get("elev_mm"), (int, float))
                  and not isinstance(op.get("elev_mm"), bool)]
    return (0.0, 0.0, min(elevations) if elevations else 0.0)


def base_digest(datums: Sequence[Mapping[str, Any]], sections: Any,
                evicted: int) -> str:
    """Подпись ВСЕГО, что способно изменить УЖЕ ОТПРАВЛЕННЫЕ элементы.

    Дельта законна ровно тогда, когда прошлое неизменно. Каналов, через
    которые новая программа меняет старый элемент, ровно три, и все три
    здесь:

      * ДАТУМЫ. `create_level` задаёт отметку, на которую ссылаются по имени
        программы, пришедшие РАНЬШЕ. Журнал держит их отдельно
        (`_DATUM_OPS`), поэтому их состояние снимается точно;
      * СНИМОК ТИПОВ. Толщина стены и наружный диаметр трубы приходят из
        типа; `remember_sections` может обновить снимок в любой момент, и
        тогда тела ВСЕХ элементов пересчитываются;
      * ВЫТЕСНЕНИЕ. Журнал ограничен; вытеснение с головы убирает программы,
        которые у клиента уже нарисованы.

    Чего здесь НЕТ и почему это законно: ссылки `ref` по правилу компилятора
    (`KIR-L003`) не выходят за пределы своей программы, поэтому программа не
    может переопределить чужой элемент.

    ЧЕГО ДЕЛЬТА НЕ ПЕРЕСЧИТЫВАЕТ, И ЭТО НАЗВАНО В ЗАГОЛОВКЕ СЦЕНЫ: `preview`
    судит выбросы (`FAR_OUTLIER`) и совпадающие стены по ВСЕМУ листу, значит
    новая программа способна изменить эти ПОМЕТКИ у старых элементов. Сцена
    их сегодня не переносит вовсе, поэтому на её содержимое это не влияет; но
    как только они поедут в буфер, они станут четвёртым каналом.
    """
    payload = {
        "schema": "kir-live-base/1",
        "datums": [_canonical(op) for op in datums],
        "sections": None if sections is None else _canonical(sections),
        "evicted": int(evicted),
    }
    return hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()[:32]


def programs_since(device_id: str | None, doc_key: str = "",
                   since: int = 0) -> tuple[list[Any], dict[str, Any]]:
    """Программы сессии, начиная с `seq >= since`. Транспорт изменений целиком.

    Своего diff-протокола нет и не будет: `SessionJournal` уже нумерует
    программы (`seq`, `next_seq`) и уже переживает пропущенный опрос. Клиент
    держит курсор и присылает его обратно — потерянный опрос стоит одного
    кадра, а не одной программы.

    Второе значение — справка, и она обязательна: клиент, получивший пустой
    список, должен отличать «ничего не менялось» от «сессии нет» и от
    «программы вытеснены и их уже не покажут».
    """
    from kukai.live import journal as _journal

    session = _journal.get(_journal.key_for(device_id, doc_key))
    if session is None:
        return [], {"session": False,
                    "reason": "сессии с таким ключом в журнале нет",
                    "next_seq": 0, "evicted": 0, "sections": False}
    fresh = [rec for rec in session.records if rec.seq >= since]
    sections = getattr(session, "sections", None)
    note = {
        "session": True,
        # ────────────────────────────────────────────────────────────────
        # СРЕЗ ПО КУРСОРУ — ЭТО ХВОСТ, А НЕ ЗДАНИЕ. НАЙДЕНО 11.08 У СЕБЯ.
        # ────────────────────────────────────────────────────────────────
        # `since > 0` возвращает ТОЛЬКО программы после курсора, и сцена из
        # них собирается как полноценная: заголовок несёт `elements`,
        # перепись сходится, картинка рисуется. Замер на журнале из двух
        # программ: `since=1` даёт здание из ОДНОГО элемента, `since=2` —
        # ПУСТОЕ здание, и ни одно из двух не отличается по форме от
        # настоящего. Клиент, ведущий курсор, показал бы дом, из которого
        # молча исчезло всё до курсора.
        #
        # Дельты сцены сегодня НЕТ: `scene_from_programs` умеет строить
        # только целое. Поэтому здесь не «почти дельта», а НАЗВАННЫЙ хвост:
        # `partial` едет в заголовок, клиент обязан либо применять его как
        # добавку к своей базе, либо запрашивать `since=0`. Молчаливая
        # половина здания — ровно тот дефект, против которого написан весь
        # этот экран, и он был мой.
        "partial": since > 0,
        "since": since,
        "next_seq": session.next_seq,
        "held": len(session.records),
        "returned": len(fresh),
        "evicted": session.programs_evicted,
        "stage": "planned",
        "assertion": "self_reported",
        # НАЛИЧИЕ СНИМКА — ГЛАВНОЕ ЧИСЛО ЭТОГО ЭКРАНА, а не деталь: без него
        # тел не будет ни у одного элемента (замер: 0 из 7).
        "sections": bool(sections),
        "sections_ru": ("снимок типов открытой модели ЕСТЬ: тела строятся из "
                        "толщин и сечений типов"
                        if sections else
                        "снимка типов открытой модели НЕТ: толщины стен и "
                        "диаметры труб живут в ТИПЕ, поэтому тел не будет ни "
                        "у одного элемента — только контуры плана"),
    }
    if since > 0:
        note["partial_ru"] = (
            f"ЭТО ХВОСТ ЖУРНАЛА, А НЕ ЗДАНИЕ: показаны только программы с "
            f"seq >= {since} ({len(fresh)} из {len(session.records)}). "
            f"Всё, что было раньше, в этой сцене ОТСУТСТВУЕТ. Для полного "
            f"здания нужен since=0")
    if session.programs_evicted:
        # ВЫТЕСНЕНИЕ НАЗЫВАЕТСЯ. Сцена без первых программ и сцена, где их не
        # было, выглядят одинаково — ровно то молчание, которое запрещено.
        note["truncated_ru"] = (
            f"{session.programs_evicted} программ вытеснено из журнала и в "
            f"сцене их НЕТ")
    return fresh, note


def _ops_of(item: Any) -> list[Mapping[str, Any]]:
    """`ProgramRecord` | `{"ops": …}` | список -> список операций."""
    raw = getattr(item, "ops", None)
    if raw is None and isinstance(item, Mapping):
        raw = item.get("ops")
    if raw is None and isinstance(item, Sequence) and not isinstance(
            item, (str, bytes)):
        raw = item
    return [op for op in (raw or ()) if isinstance(op, Mapping)]


def _qualify(pack: Sequence[Sequence[Mapping[str, Any]]],
             *, first_position: int = 1) -> list[list[dict[str, Any]]]:
    """Пачка -> та же пачка с адресами масштаба ПАЧКИ (`p1/w0`).

    Переписываются `id` и КАЖДАЯ ссылка `{"by": "ref", "value": …}`. Обход
    рекурсивный, потому что ссылки живут и в списках (`refs_w`), и во
    вложенных словарях, а список имён полей («host», «level», «wall»)
    разъехался бы с реестром на первой же новой операции — и разъехался бы
    МОЛЧА. Тот же довод, по которому `live.transfer.refs_of` читает
    `spec.OPS[...].params`, а не список имён.

    БЕЗОПАСНОСТЬ ТОТАЛЬНОСТИ. `ref` по правилу компилятора (`KIR-L003`)
    указывает только на более ранний оп ТОЙ ЖЕ программы. Ссылок наружу не
    бывает, поэтому одинаковый префикс у цели и у ссылки сохраняет все связи,
    а адреса между программами перестают сталкиваться.
    """
    from kukai.ir.clash_bundle import bundle_oid

    def walk(value: Any, prefix: str) -> Any:
        if isinstance(value, Mapping):
            if value.get("by") == "ref" and isinstance(value.get("value"), str):
                return {**value, "value": f"{prefix}{value['value']}"}
            return {k: walk(v, prefix) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [walk(v, prefix) for v in value]
        return value

    out: list[list[dict[str, Any]]] = []
    for position, ops in enumerate(pack, start=first_position):
        # Префикс берётся ИЗ `bundle_oid`, а не собирается здесь: разделитель
        # принадлежит адресу, и вторая его копия — это второй формат адреса.
        prefix = bundle_oid(position, "")
        program: list[dict[str, Any]] = []
        for op in ops:
            fresh = {k: walk(v, prefix) for k, v in op.items() if k != "id"}
            if op.get("id"):
                fresh["id"] = f"{prefix}{op['id']}"
            program.append(fresh)
        out.append(program)
    return out


def _z_of(op: Mapping[str, Any] | None, base_mm: float
          ) -> tuple[float, float, bool]:
    """(z0, z1, высота известна?) — и третье значение НЕ декоративно."""
    if op is None:
        return base_mm, base_mm + FALLBACK_HEIGHT_MM, False
    offset = 0.0
    for name in _BASE_FIELDS:
        value = op.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            offset = float(value)
            break
    for name in _HEIGHT_FIELDS:
        value = op.get(name)
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and value):
            z0 = base_mm + offset
            return z0, z0 + abs(float(value)), True
    z0 = base_mm + offset
    return z0, z0 + FALLBACK_HEIGHT_MM, False


def scene_from_programs(programs: Sequence[Any], *, doc_key: str = "",
                        snapshot: Any = None,
                        journal: Mapping[str, Any] | None = None,
                        origin_mm: tuple[float, float, float] | None = None,
                        first_position: int = 1,
                        session_key: tuple[str, str] | None = None,
                        whole: bool = True,
                        context_programs: int = 0
                        ) -> tuple[bytes, dict[str, Any]]:
    """Программы -> байты сцены. Тот же кодек, словарь честности и тракт
    геометрии, что у разобранного здания."""
    from kukai.clash import geom as G
    from kukai.clash import hulls as HU
    from kukai.clash import snapshot as S
    from kukai.ir import clash_bundle as CB
    from kukai.ir import preview as P

    started = time.perf_counter()
    # ДВА ПОТРЕБИТЕЛЯ, И КВАЛИФИЦИРУЕТ ТОЛЬКО ОДИН ИЗ НИХ САМ.
    # `bundle_elements` адресует элементы `bundle_oid`-ом ВНУТРИ СЕБЯ, поэтому
    # ему отдаётся СЫРАЯ пачка: подать ему уже квалифицированную значит
    # получить `p1/p1/w0`. Замер 11.08 (этот дефект и был им пойман): пять
    # труб приезжали в сцену ДВАЖДЫ — телом под двойным адресом и призраком
    # под одинарным, и перепись показывала 13 элементов там, где их 8.
    # `preview` своего адреса не строит вовсе, поэтому ему отдаётся пачка,
    # квалифицированная ЗДЕСЬ, — и тогда оба говорят `p1/w0` об одном элементе.
    raw = [_ops_of(item) for item in programs]
    # НОМЕР ПРОГРАММЫ — В МАСШТАБЕ СЕССИИ, А НЕ СРЕЗА. Дельта, начавшая
    # нумерацию заново с `p1`, выдала бы новым элементам адреса, которые у
    # клиента уже заняты старыми, и склейка молча ПОДМЕНИЛА бы их. Адрес
    # обязан зависеть только от того, к чему он ведёт.
    flat: list[Mapping[str, Any]] = [
        op for ops in _qualify(raw, first_position=first_position) for op in ops]

    # ── 1. ТЕЛА. Строит `clash_bundle`, а не этот модуль.
    # `bundle_elements` нумерует пачку С ЕДИНИЦЫ и своего смещения не знает.
    # Выравнивание делается ПОДСТАВНЫМИ пустыми программами впереди: пустая
    # программа не создаёт ни элемента, ни причины безтелесности, поэтому
    # сдвиг адресов достаётся даром и без правки чужого модуля.
    geometry = CB.bundle_elements([[]] * (first_position - 1) + list(raw),
                                  snapshot=snapshot)
    hulls = S.build_from_elements(geometry.elements,
                                  origin={"doc_key": doc_key or "живая сессия"},
                                  profiles=geometry.profiles)
    body = {rec.source_id: rec for rec in hulls.records}
    # Отказ ПОЭЛЕМЕНТНО приходит отсюда — это единственная поимённая причина,
    # которая у нас есть. Класс (`BLIND_CLASS_RU`) считается пачкой и потому
    # едет распределением, а не на элементе.
    refused = {ref.source_id: ref.reason for ref in hulls.refusals}

    # ── 2. КОНТУРЫ ПЛАНА. Запасной путь для бестелесных и источник этажей.
    building = P.build_program_preview(flat)
    op_by_id = {str(op.get("id")): op for op in flat if op.get("id")}
    # ── СЛОЙ ГРАФА ДЛЯ ЗАЯВЛЕННОГО. `existence=planned` — то, ради чего
    #    существует эта половина: инженер три часа строит здание, которого в
    #    Revit ещё нет, и непостроенное обязано быть ОТЛИЧИМО от построенного.
    graph_facts, graph_note = _graph.facts_for_programs(op_by_id)
    unproven = _honesty.unproven_ops()
    census = _honesty.HonestyCensus()
    axes_cache: dict[str, int] = {}
    axes_tally: dict[int, int] = {}
    height_unknown = 0
    drawn: set[str] = set()

    def axes_for(op_name: str) -> int:
        if op_name not in axes_cache:
            axes_cache[op_name] = _honesty.axes_byte(
                _honesty.axes_for_ops([op_name]))
        return axes_cache[op_name]

    # ── 3. ОБЩЕЕ НАЧАЛО по обоим источникам сразу, иначе тела и контуры
    #      разъедутся в разные начала координат и здание рассыплется.
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for rec in hulls.records:
        lo, hi = rec.bounds()
        xs += [lo[0], hi[0]]
        ys += [lo[1], hi[1]]
        zs += [lo[2], hi[2]]
    for plan in building.plans:
        extents = plan.extents_mm()
        if extents:
            xs += [extents[0], extents[2]]
            ys += [extents[1], extents[3]]
        if plan.level_elevation_mm is not None:
            zs.append(float(plan.level_elevation_mm))
    # ЗАКРЕПЛЁННОЕ НАЧАЛО СТАРШЕ ВЫЧИСЛЕННОГО. Дельта обязана лечь в ту же
    # систему координат, что и база; начало, посчитанное по габариту среза,
    # сдвинуло бы её на величину, которую никто не заметит.
    origin = origin_mm if origin_mm is not None else (
        (min(xs) + max(xs)) * 0.5 if xs else 0.0,
        (min(ys) + max(ys)) * 0.5 if ys else 0.0,
        min(zs) if zs else 0.0)
    far = max((abs(v - o) for vals, o in ((xs, origin[0]), (ys, origin[1]),
                                          (zs, origin[2])) for v in vals),
              default=0.0)
    builder = SceneBuilder(origin_mm=origin)

    def place(element_id: str, category: str, level: Any, op_name: str,
              kind: int, slot: int, fidelity: _honesty.Fidelity,
              why: str) -> None:
        trust = (_honesty.Trust.UNKNOWN if not unproven
                 else (_honesty.Trust.OP_UNPROVEN if op_name in unproven
                       else _honesty.Trust.OP_PROVEN))
        axes = axes_for(op_name) if op_name else _honesty.AXES_UNJUDGEABLE
        axes_tally[axes] = axes_tally.get(axes, 0) + 1
        census.add(_honesty.ElementHonesty(
            element_id=element_id, trust=trust, fidelity=fidelity, why=why))
        node = graph_facts.get(element_id)
        builder.add_element(
            element_id=element_id, category=category, level=level,
            trust=TRUST_CODE[trust.value],
            fidelity=FIDELITY_CODE[fidelity.value],
            kind=kind, slot=slot, label=op_name, axes=axes,
            authority=_graph.AUTHORITY_CODE.get(
                node.authority if node else "unknown", 2),
            existence=_graph.EXISTENCE_CODE.get(
                node.existence if node else "unknown", 2),
            flags=node.flags if node else 0)
        drawn.add(element_id)

    # ── 4. ТЕЛА В СЦЕНУ. Тот же разбор примитивов, что в `scene.py`.
    for rec in hulls.records:
        hull = rec.hull
        if isinstance(hull, G.Capsule):
            kind, slot = builder.add_capsule(hull.path, hull.radius)
        elif isinstance(hull, G.PrismSet):
            kind, slot = builder.add_prism(hull.pieces, hull.z0, hull.z1)
        elif isinstance(hull, G.Prism):
            kind, slot = builder.add_prism((hull.footprint,), hull.z0, hull.z1)
        else:
            lo, hi = rec.bounds()
            kind, slot = builder.add_box(lo, hi)
        op = op_by_id.get(rec.source_id) or {}
        place(rec.source_id, rec.category, rec.level_id,
              str(op.get("op") or ""), kind, slot,
              _honesty.fidelity_of(rec.grade, rec.hull_source,
                                   HU.hull_degeneracy(hull)),
              str(op.get("op") or ""))

    # ── 5. БЕСТЕЛЕСНЫЕ — контуром плана и ПРИЗРАКОМ, а не пропуском.
    for plan in building.plans:
        base = float(plan.level_elevation_mm or 0.0)
        for element in plan.elements:
            if element.element_id in drawn:
                continue
            op = op_by_id.get(element.element_id)
            z0, z1, known = _z_of(op, base)
            if not known:
                height_unknown += 1
            placed = _extrude(builder, element, z0, z1)
            if placed is None:
                continue
            kind, slot = placed
            place(element.element_id, element.category, plan.level_name,
                  str((op or {}).get("op") or ""), kind, slot,
                  _honesty.Fidelity.NO_BODY,
                  refused.get(element.element_id)
                  or ("height_unknown" if not known else "тела нет"))
    # ── СВЕРКА ПЛАНА И ОБЪЁМА. Обе переписи уже построены выше, поэтому
    #    сверке остаётся раскладка: замер 5.5 мс на 6 000 элементов против
    #    213 мс bundle и 84 мс preview, которые платятся всё равно. В пути
    #    дельты кадр строит только новые программы, значит раскладка O(нового).
    #    Знаменатель — ВСЕ написанные операции: иначе четвёртая корзина пуста
    #    по построению.
    context_ids = {str(op.get("id")) for ops in _qualify(
        raw[:context_programs], first_position=first_position)
        for op in ops if op.get("id")} if context_programs else set()
    recon = {"available": False, "reason": "сессия не названа: сверять нечего"}
    if session_key is not None:
        try:
            recon = _reconcile.live_frame(
                session_key,
                # КОНТЕКСТНЫЕ ДАТУМЫ ИЗ ЗНАМЕНАТЕЛЯ ИСКЛЮЧЕНЫ. Они едут с
                # КАЖДОЙ дельтой (без `create_level` у среза нет отметки), и
                # каждый раз получают адрес своей позиции — то есть НОВЫЙ.
                # Найдено своим же замером: `neither` рос на единицу с каждой
                # дельтой, а за трёхчасовую сессию набрал бы сотни призраков.
                # Это контекст, а не написанная в этом кадре работа.
                ops_by_id={oid: str(op.get("op") or "")
                           for oid, op in op_by_id.items()
                           if oid not in context_ids},
                drawn={str(e.element_id) for plan in building.plans
                       for e in plan.elements},
                # ДАТУМЫ СЧИТАЮТСЯ НАРИСОВАННЫМИ: `preview` держит их отдельным
                # списком, и не заглянуть туда значило бы объявить ось
                # невидимой ровно там, где план её показывает.
                datums={str(e.element_id) for plan in building.plans
                        for e in plan.datums},
                bodied={rec.source_id for rec in hulls.records},
                refused={ref.source_id: ref.reason for ref in hulls.refusals},
                no_body_ops=dict(geometry.no_body),
                whole=whole)
        except Exception as exc:  # noqa: BLE001 — сверка не роняет кадр
            recon = {"available": False,
                     "reason": f"сверка не собралась: {type(exc).__name__}"}
    return _finish(builder, census, building, geometry, hulls, axes_tally,
                   height_unknown, doc_key, snapshot, flat, started, journal,
                   graph_note, far, session_key, whole, recon)


def _finish(builder, census, building, geometry, hulls, axes_tally,
            height_unknown, doc_key, snapshot, flat, started, journal,
            graph_note, far, session_key=None, whole=True, recon=None
            ) -> tuple[bytes, dict[str, Any]]:
    """Заголовок сцены. Всё, чего в картинке НЕТ, называется здесь."""
    from kukai.ir import clash_bundle as CB
    from kukai.ir import preview as P
    from kukai.live import showroom as _showroom

    # ПОДПИСЬ ПОКАЗАННОГО КОПИТСЯ ВИТРИНОЙ, А НЕ СЧИТАЕТСЯ ЗАНОВО. Целая
    # сцена обнуляет накопление, хвост — дописывается; сервер добавляет РОВНО
    # записи новых элементов и остаётся O(нового) на кадр. Пересчёт по всей
    # сцене вернул бы кадру стоимость целого, то есть починил бы транспорт и
    # сломал бы его же кнопкой.
    shown = ""
    if session_key is not None:
        try:
            shown = _showroom.scene_shown(
                session_key, builder.shown_records(),
                elements=builder.count, whole=whole)
        except Exception:  # noqa: BLE001 — витрина не имеет права ронять кадр
            shown = ""

    # КЛАСС ПРИЧИНЫ СЧИТАЕТ ВЛАДЕЛЕЦ ТАБЛИЦЫ. Своя копия шести строк
    # (`never_a_body` из `no_body`, остальное из `no_geometry`) разошлась бы с
    # оригиналом молча — тот же довод, по которому `unwitnessed_axes` не
    # копируется, а вызывается.
    by_class = CB._blind_by_class(geometry)
    bodies = len(hulls.records)
    declared = bodies + len(hulls.refusals)
    meta: dict[str, Any] = {
        "run": doc_key or "(живая сессия)",
        "source": "program",
        "stage": "planned",
        "assertion": "self_reported",
        "assertion_ru": ("ЗАЯВЛЕНО программами сессии — модель не читалась, "
                         "в Revit этого ещё нет"),
        "trust_codes": TRUST_CODE,
        "fidelity_codes": FIDELITY_CODE,
        "honesty": census.to_dict(),
        "honesty_source": {"available": bool(_honesty.unproven_ops()),
                           "unproven_table": bool(_honesty.unproven_ops())},
        "census": building.census.to_dict(),
        "levels_total": building.levels_total,
        "levels_rendered": len(building.plans),
        "programs": len({str(op.get("id", "")).split("/")[0]
                         for op in flat if op.get("id")}),
        "ops": len(flat),
        # ── ПОКРЫТИЕ ТЕЛАМИ. Первое число экрана, а не сноска.
        "bodies": bodies,
        "bodies_declared": declared,
        "bodies_pct": (round(100.0 * bodies / declared, 2) if declared else 0.0),
        "bodies_ru": (f"{bodies} тел из {declared} объявленных элементов"
                      if declared else "элементов с телом не объявлено"),
        "blind_by_class": by_class,
        "blind_class_ru": dict(CB.BLIND_CLASS_RU),
        # ДЫРА В ЧУЖОЙ ТАБЛИЦЕ ВИДНА НА ЭКРАНЕ, а не только в тесте: причина
        # без класса читается как отсутствие проблемы.
        "blind_unclassified": by_class.get("unclassified", 0),
        "blind_scope_ru": ("класс причины считается ПАЧКОЙ: на элементе сказано "
                           "«тела нет» и отказ построителя оболочек, а класс — "
                           "распределением по сессии"),
        "sections_present": bool(snapshot),
        "sections_ru": ("снимок типов открытой модели ЕСТЬ"
                        if snapshot else
                        "снимка типов открытой модели НЕТ: без него тела не "
                        "строятся почти ни у чего — замер 0 из 7 на пачке "
                        "стен и трубы"),
        "height_unknown": height_unknown,
        "height_unknown_ru": (
            f"{height_unknown} элементов без высоты в программе: им поставлена "
            f"заглушка {FALLBACK_HEIGHT_MM:.0f} мм, это НЕ их высота"),
        "axes_order": list(_honesty.AXES_ORDER),
        "axes_unjudgeable": _honesty.AXES_UNJUDGEABLE,
        "axes_tally": {str(k): v for k, v in sorted(axes_tally.items())},
        "axes_ru": ("оси, по которым операция НЕ ОБЪЯВИЛА обязательств: "
                    "зелёный по ним не значит проверено"),
        "declaration_slack": len(geometry.declaration_slack),
        "id_collisions": geometry.collisions,
        "blind_spots": LIVE_BLIND_SPOTS + P.BLIND_SPOTS,
        # СПРАВКА ЖУРНАЛА КЛАДЁТСЯ ДО `finish`, А НЕ ПОСЛЕ. Заголовок лежит
        # ВНУТРИ байтов сцены; дописанное в `meta` после упаковки видит только
        # сервер, а клиент — никогда. Замер 11.08: вытеснение программ и
        # отсутствие снимка доезжали до сервера и НЕ доезжали до экрана, то
        # есть предупреждение существовало и молчало.
        "journal": dict(journal) if journal else None,
        # ХВОСТ НАЗЫВАЕТСЯ И В КОРНЕ. Потребителю, читающему верхний уровень
        # заголовка, не полагается догадываться, что здание неполно.
        "partial": bool(journal.get("partial")) if journal else False,
        "delta": bool(journal.get("delta")) if journal else False,
        "base_digest": (journal or {}).get("base_digest", ""),
        # ПОДПИСЬ ТОГО, ЧТО ЧЕЛОВЕК ВИДИТ. Пустая строка значит «витрина не
        # спрошена» (сцена собрана вне сессии), и это НЕ «подписывать нечего»:
        # кнопка на такой сцене обязана отказать, а не согласиться.
        "shown_digest": shown,
        "shown_ru": ("подпись СКЛЕЙКИ, накопленной витриной; панель обязана "
                     "посчитать свою по нарисованному и прислать её кнопке"),
        # ТОЧНОСТЬ СМЕЩЕНИЯ ПРОВЕРЯЕТСЯ, А НЕ ОБЕЩАЕТСЯ. За этим радиусом
        # float32 перестаёт представлять миллиметр точно, и склейка дельты с
        # базой поехала бы субмиллиметрово — то есть незаметно.
        "origin_overflow": bool(far > FLOAT32_EXACT_MM),
        "origin_far_mm": round(float(far), 1),
        "partial_ru": (journal or {}).get("partial_ru", ""),
        "graph": graph_note,
        # СВЕРКА ЕДЕТ В КАДРЕ, потому что здесь она почти ничего не стоит:
        # обе переписи уже построены этим же вызовом. У разбора она стоила их
        # суммы и потому живёт отдельным входом — разная цена, разное место.
        "reconcile": recon or {"available": False,
                               "reason": "сверка не запрашивалась"},
        "authority_codes": _graph.AUTHORITY_CODE,
        "existence_codes": _graph.EXISTENCE_CODE,
        "flag_bits": {"refuted": _graph.FLAG_REFUTED,
                      "unresolved": _graph.FLAG_UNRESOLVED},
        "flags_ru": {"refuted": "у элемента ОПРОВЕРГНУТО отношение (сам "
                                "элемент цел)",
                     "unresolved": "у элемента есть отношение, чья ЦЕЛЬ вне "
                                   "извлечения"},
        "timing_ms": {"total": round((time.perf_counter() - started) * 1000, 1)},
    }
    blob = builder.finish(meta)
    meta["bytes"] = len(blob)
    return blob, meta


def _extrude(builder: SceneBuilder, element: Any, z0: float, z1: float):
    """`DrawnElement` -> примитив сцены. Разбор по ФОРМЕ, а не по категории.

    Формы `preview` закрыты (`Poly | Path | Dot | TextMark`), поэтому разбор
    полон по построению, а не по перечислению категорий, которое разъехалось
    бы с реестром на первой же новой операции.
    """
    from kukai.ir import preview as P

    for shape in element.shapes:
        if isinstance(shape, P.Poly) and shape.loops and len(shape.loops[0]) >= 3:
            # Дыры контура (`loops[1:]`) НЕ вычитаются: булевых операций в
            # `clash.geom` нет, и заводить их здесь значило бы завести вторые.
            # Внешний контур — надмножество, тот же закон консервативности,
            # что у оболочек.
            return builder.add_prism((tuple(shape.loops[0]),), z0, z1)
        if isinstance(shape, P.Path) and len(shape.pts) >= 2:
            # Ломаная без толщины -> капсула тонкого радиуса: у оси нет
            # сечения, и придумывать ей ширину нельзя.
            return builder.add_capsule(
                [(x, y, z0) for x, y in shape.pts], max(1.0, (z1 - z0) * 0.02))
        if isinstance(shape, P.Dot):
            x, y = shape.xy
            r = max(shape.r_mm, 1.0)
            return builder.add_box((x - r, y - r, z0), (x + r, y + r, z1))
    return None


def scene_from_session(device_id: str | None, doc_key: str = "",
                       since: int = 0, base: str = ""
                       ) -> tuple[bytes, dict[str, Any]]:
    """Живая сессия: целое при `since=0`, ДЕЛЬТА при `since>0`.

    Снимок берётся ИЗ ЖУРНАЛА, а не из параметра: его туда кладёт
    `plan_stream.remember_sections`, и второй источник снимка означал бы, что
    картинка строится по одному документу, а перенос в Revit — по другому.

    ────────────────────────────────────────────────────────────────────────
    ДОГОВОР ДЕЛЬТЫ, И ОН ОТКАЗЫВАЕТ, А НЕ ДОГАДЫВАЕТСЯ
    ────────────────────────────────────────────────────────────────────────
    Клиент держит курсор `since` и подпись базы `base`. Дельта выдаётся
    ТОЛЬКО когда подпись сходится с текущей: `base_digest` покрывает всё, что
    способно изменить уже отправленные элементы (датумы, снимок типов,
    вытеснение). Разошлась — `StaleBase`, и клиент обязан перезапросить
    целое. Приклеить хвост к чужой базе значит показать здание, которого
    никогда не существовало; пустой экран хотя бы виден.

    `since>0` без подписи тоже отказ, а не «наверное подойдёт»: молчаливое
    согласие на неизвестную базу — это та же склейка, только с ленью вместо
    ошибки.
    """
    from kukai.live import journal as _journal

    session = _journal.get(_journal.key_for(device_id, doc_key))
    snapshot = getattr(session, "sections", None) if session else None
    datums = list(getattr(session, "datums", ()) or ()) if session else []
    evicted = getattr(session, "programs_evicted", 0) if session else 0
    digest = base_digest(datums, snapshot, evicted)
    origin = live_origin(datums)

    if since > 0 and base != digest:
        raise StaleBase(
            "база клиента не та, к которой применима дельта: "
            f"ожидалась {digest}, пришла {base or '(пусто)'}. "
            "Изменились датумы, снимок типов или журнал вытеснил программы. "
            "Нужен полный запрос since=0 — приклеивать хвост к чужой базе "
            "нельзя")

    programs, note = programs_since(device_id, doc_key, since)
    note["base_digest"] = digest
    note["delta"] = since > 0
    # ДАТУМЫ ЕДУТ КОНТЕКСТОМ, А НЕ ЭЛЕМЕНТАМИ. Без `create_level` у среза нет
    # отметки этажа, и новые элементы легли бы на нулевую — то есть дельта
    # рисовала бы верно только первый этаж. Журнал держит датумы отдельно
    # ровно за этим (`_DATUM_OPS`), и `plan_stream._slice_for` берёт их так же.
    context = [{"ops": datums}] if (since > 0 and datums) else []
    blob, meta = scene_from_programs(
        context + list(programs), doc_key=doc_key, snapshot=snapshot,
        journal=note, origin_mm=origin,
        session_key=_journal.key_for(device_id, doc_key), whole=(since == 0),
        context_programs=len(context),
        # Контекстная программа занимает нулевую позицию, поэтому настоящие
        # начинаются со своего места в сессии — адреса совпадают с базой.
        first_position=(since - len(context) + 1) if since > 0 else 1)
    meta["context_ops"] = len(datums) if context else 0
    return blob, meta
