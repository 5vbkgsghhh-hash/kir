"""СВЕРКА ДВУХ ПЕРЕПИСЕЙ ОДНОГО ЗДАНИЯ — плана и объёма.

`preview` ведёт свою перепись листа (`OmitReason`, `ApproxReason`,
`AnomalyReason`), вьюер — свою перепись тел (классы точности, оси честности,
классы причин безтелесности). Обе внутренне сходятся. Инженер смотрит на них
рядом и считает, что это одно здание.

════════════════════════════════════════════════════════════════════════════
ЗАМЕР 11.08.2026 — И ОН ОТМЕНИЛ ЗАДАЧУ «СВЕСТИ ПЕРЕПИСИ В ОДНУ»
════════════════════════════════════════════════════════════════════════════
`sob62_fas_r23_v19`: план рисует 4 285 из 5 218; объём даёт тело 4 218 из
5 001. Пересечение 3 948, только план 337, только объём 270.

`snowdon_plumb_v4`: план 26 258 из 32 185; объём 31 904 из 32 063.
Пересечение 26 203, только план 55, **только объём 5 701**.

Расхождения разобраны поимённо, и все три класса оказались ЗАКОННЫМИ — то
есть переписи отвечают на РАЗНЫЕ вопросы, а не на один по-разному:

1. **ДАТУМЫ, АННОТАЦИИ, ПОМЕЩЕНИЯ, ПРОСТРАНСТВА** — 217 на фасаде, 122 на
   инженерии. План их рисует (ось на плане нужна), объём объявляет
   `not_eligible` (тела у них нет). Вопросы разные: «видно ли это на срезе»
   против «есть ли у этого тело».

2. **ВЕРТИКАЛЬНЫЕ УЧАСТКИ** — 5 506 труб и 195 воздуховодов
   `snowdon_plumb_v4`, то есть **21 % здания**. Объём рисует их капсулами,
   план честно объявляет `degenerate`: стояк проецируется в точку, и
   нарисовать его на срезе нечем. Это свойство ПРОЕКЦИИ, а не потеря.

3. **СТЕНЫ С ОСЬЮ, НО БЕЗ ГАБАРИТА** — 291 из 2 360 (12.3 %) на фасаде.
   Замер точный: у всех 291 `bbox_min_mm`/`bbox_max_mm` в L0 отсутствуют, а
   ось в `curve.index.json` есть у всех 291. План рисует их линией с меткой
   `thickness_unknown`; `hulls.KIND_TABLE` разрешает стене только `bbox`
   (замок содержания не открыт — 97 нарушений на 800 настоящих стенах),
   поэтому оболочки не будет. И здесь вопросы разные: «могу ли я провести
   линию» против «могу ли я ОГРАНИЧИТЬ тело». Ось без толщины не содержит
   стену, а оболочка обязана содержать.

**ВЫВОД: СВОДИТЬ ПЕРЕПИСИ НЕ НАДО, И БЫЛО БЫ НЕПРАВДОЙ.** Общий знаменатель
заставил бы одну из них отвечать на чужой вопрос: либо план начал бы считать
стояки потерей, либо объём — датумы. Обе стали бы врать ради согласия.

════════════════════════════════════════════════════════════════════════════
ЧТО НАДО ВМЕСТО ЭТОГО, И ЧЕГО СЕГОДНЯ НЕТ ВООБЩЕ
════════════════════════════════════════════════════════════════════════════
Надо НАЗВАТЬ РАЗЛИЧИЕ. Сегодня о нём не сказано нигде: инженер видит на плане
291 стену, которых в объёме нет, и 5 506 труб в объёме, которых нет на плане,
и ни один экран не сообщает, что второй показывает другое.

Этот модуль — не третья перепись. Он ничего не считает сам: он спрашивает обе
и раскладывает КАЖДЫЙ элемент ровно в одну из четырёх корзин, забирая причину
у той переписи, которая её назвала. Закон сходимости тот же, что у обеих
родительских, и он проверяется, а не обещается:

    объединение = оба + только_план + только_объём + ни_один

Расхождение здесь — ошибка, а не предупреждение: сверка, у которой элемент
не попал ни в одну корзину, скрывает ровно тот случай, ради которого её
писали.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ("RECONCILE_SCHEMA", "Bucket", "Reconciliation", "reconcile_run")

RECONCILE_SCHEMA = "kir-viewer-reconcile/1"


class Bucket:
    """Четыре корзины. Список закрыт: элемент, не попавший ни в одну, —
    молчаливое выпадение, и перепись обязана его поймать."""

    BOTH = "both"
    PLAN_ONLY = "plan_only"
    SCENE_ONLY = "scene_only"
    NEITHER = "neither"


BUCKET_RU: dict[str, str] = {
    Bucket.BOTH: "видно и на плане, и в объёме",
    Bucket.PLAN_ONLY: ("нарисовано планом, тела в объёме НЕТ — на двух экранах "
                       "разное здание, и вот причина"),
    Bucket.SCENE_ONLY: ("есть тело в объёме, планом НЕ нарисовано — обычно "
                        "стояк (в срез проецируется точкой) или элемент без "
                        "этажа"),
    Bucket.NEITHER: "ни один экран этого не показывает",
}


@dataclass
class Reconciliation:
    """Раскладка каждого элемента ровно в одну корзину + причины и переписи."""

    run: str = ""
    buckets: dict[str, int] = field(default_factory=dict)
    #: Корзина -> категория -> сколько. Категория здесь не украшение: 291
    #: стены и 46 осей попали в `plan_only` по РАЗНЫМ причинам, и слить их в
    #: одно число значило бы спрятать ту, которая чинится.
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    #: Корзина -> названная причина -> сколько. Причина берётся у той переписи,
    #: которая её назвала: у объёма для `plan_only`, у плана для `scene_only`.
    by_reason: dict[str, dict[str, int]] = field(default_factory=dict)
    examples: dict[str, list[str]] = field(default_factory=dict)
    plan_census: dict[str, Any] = field(default_factory=dict)
    scene_census: dict[str, Any] = field(default_factory=dict)
    union: int = 0
    elapsed_ms: float = 0.0
    note: str = ""

    def balanced(self) -> bool:
        """Сходимость СВЕРКИ. Элемент, не попавший ни в одну корзину, — это
        ровно тот случай, ради которого сверка и написана."""
        return sum(self.buckets.values()) == self.union

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RECONCILE_SCHEMA,
            "run": self.run,
            "union": self.union,
            "buckets": dict(sorted(self.buckets.items())),
            "bucket_ru": BUCKET_RU,
            "by_category": {k: dict(sorted(v.items(), key=lambda kv: -kv[1]))
                            for k, v in sorted(self.by_category.items())},
            "by_reason": {k: dict(sorted(v.items(), key=lambda kv: -kv[1]))
                          for k, v in sorted(self.by_reason.items())},
            "examples": {k: v[:5] for k, v in sorted(self.examples.items())},
            "plan_census": self.plan_census,
            "scene_census": self.scene_census,
            "balanced": self.balanced(),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "note": self.note,
            "verdict_ru": (
                "переписи НЕ СВОДЯТСЯ в одну намеренно: план отвечает «видно "
                "ли это на срезе», объём — «есть ли у этого тело». Общий "
                "знаменатель заставил бы одну из них считать потерей то, что "
                "потерей не является"),
        }


def reconcile_run(run: str) -> Reconciliation:
    """Сверить план и объём одного разбора. Читает оба источника, свой — ноль.

    ЦЕНА НАЗВАНА: строятся ОБЕ переписи целиком, поэтому сверка стоит суммы
    их стоимостей (фасад — 0.8 с план + 0.3 с объём). Поэтому она живёт
    ОТДЕЛЬНЫМ входом и не едет в каждый кадр сцены: сцена вместо этого
    честно говорит, что сверка не запрашивалась.
    """
    from kukai.clash import snapshot as S
    from kukai.ir import preview as P
    from kukai.viewer.scene import run_root

    started = time.perf_counter()
    base = run_root() / run
    if not base.exists():
        raise FileNotFoundError(f"разбора {run!r} нет в {run_root()}")

    building = P.preview_snapshot(base)
    plan_drawn: dict[str, str] = {}
    for sheet in building.plans:
        for element in tuple(sheet.elements) + tuple(sheet.datums):
            plan_drawn[str(element.element_id)] = element.category

    snap = S.build_from_decompile(base)
    scene_bodies = {record.source_id: record.category for record in snap.records}
    scene_refusal = {refusal.source_id: (refusal.reason or refusal.bucket)
                     for refusal in snap.refusals}
    scene_category = dict(scene_bodies)
    for refusal in snap.refusals:
        scene_category.setdefault(refusal.source_id, refusal.category)

    # ПРИЧИНЫ ПЛАНА ПОЭЛЕМЕНТНО ЕМУ НЕ ПРИНАДЛЕЖАТ. `PreviewCensus` группирует
    # опущенное по (причина, категория) и хранит лишь до пяти примеров, поэтому
    # сказать про КОНКРЕТНЫЙ элемент «план опустил его вот почему» нечем.
    # Приписать ему причину по категории было бы догадкой, надетой на элемент,
    # а догадка на элементе читается как измерение. Поэтому для `scene_only`
    # публикуется РАСПРЕДЕЛЕНИЕ причин плана, а на элементе — только факт.
    plan_reason_totals: dict[str, int] = {}
    for group in building.census.omitted:
        key = f"{group.reason.value}/{group.category}"
        plan_reason_totals[key] = plan_reason_totals.get(key, 0) + group.count

    result = Reconciliation(run=run)
    union = set(plan_drawn) | set(scene_category)
    result.union = len(union)
    for element_id in union:
        in_plan = element_id in plan_drawn
        in_scene = element_id in scene_bodies
        bucket = (Bucket.BOTH if in_plan and in_scene
                  else Bucket.PLAN_ONLY if in_plan
                  else Bucket.SCENE_ONLY if in_scene
                  else Bucket.NEITHER)
        result.buckets[bucket] = result.buckets.get(bucket, 0) + 1
        category = plan_drawn.get(element_id) or scene_category.get(element_id, "?")
        cats = result.by_category.setdefault(bucket, {})
        cats[category] = cats.get(category, 0) + 1
        if bucket in (Bucket.PLAN_ONLY, Bucket.NEITHER):
            # Причину даёт ОБЪЁМ: он отказал поимённо, и это его слова.
            reason = scene_refusal.get(element_id, "объём про этот элемент молчит")
            reasons = result.by_reason.setdefault(bucket, {})
            reasons[reason] = reasons.get(reason, 0) + 1
        if len(result.examples.setdefault(bucket, [])) < 5:
            result.examples[bucket].append(element_id)

    # Причины плана — РАСПРЕДЕЛЕНИЕМ, а не на элементе (см. выше).
    result.by_reason[Bucket.SCENE_ONLY] = dict(plan_reason_totals)
    result.plan_census = building.census.to_dict()
    result.scene_census = snap.census.as_dict()
    result.note = (
        "причины для `scene_only` даны РАСПРЕДЕЛЕНИЕМ по всему листу: "
        "`PreviewCensus` группирует опущенное и хранит до пяти примеров, "
        "поэтому поимённой причины плана у элемента нет, и придумывать её "
        "нельзя")
    result.elapsed_ms = (time.perf_counter() - started) * 1000.0
    return result


# ═══════════════════════════════════════════════════════════════════════════
# СВЕРКА ЖИВОЙ СЕССИИ — расхождение, которое инженер видит ТРИ ЧАСА
# ═══════════════════════════════════════════════════════════════════════════
#
# Разбор смотрят при открытии архива. Живую сцену смотрят всю сессию, и
# расхождение там ДРУГОЙ ПРИРОДЫ: тела зависят от снимка типов открытой
# модели, а план — нет.
#
# ЗАМЕР 11.08.2026, 300 программ / 6 000 элементов (14 труб и 6 стен на
# программу), через тот же тракт, что и сцена:
#
#     снимок ЕСТЬ:  оба 4 200, только план 1 800   (стены — замок оболочек)
#     снимок НЕТ:   только план 6 000, оба 0       ← план ПОЛОН, объём ПУСТ
#
# Вторая строка и есть тот исход, ради которого весь марафон разводили
# «прибор молчал» и «пересечений нет»: обе стороны честны поодиночке, план
# показывает всё здание, объём не показывает ничего, и никто не говорит, что
# это одно и то же здание.
#
# ЗНАМЕНАТЕЛЬ ЖИВОЙ СВЕРКИ — ВСЕ НАПИСАННЫЕ ОПЕРАЦИИ, а не те, у кого что-то
# получилось. Иначе четвёртая корзина пуста ПО ПОСТРОЕНИЮ: элемент, которого
# не создал никто, в объединение «нарисованных и оболоченных» не попадёт.
# Замер на пятиоперационной программе: по знаменателю операций «ни один» —
# 4 из 5 (`create_level`, `create_grid`, `create_room`, `set_param`).
#
# ДАТУМЫ СЧИТАЮТСЯ НАРИСОВАННЫМИ. `preview` держит их отдельным списком
# (`FloorPlan.datums`), и не заглянуть туда значило бы объявить ось невидимой
# ровно там, где план её показывает.
#
# ЦЕНА. Обе переписи в живом тракте УЖЕ ПОСТРОЕНЫ — `scene_from_programs`
# строит и `build_program_preview`, и `bundle_elements` + `build_from_elements`
# в одном вызове. Сверке остаётся раскладка: замер — 5.5 мс на 6 000 элементов
# против 213 мс bundle и 84 мс preview, которые платятся всё равно. В пути
# ДЕЛЬТЫ кадр строит только новые программы, поэтому раскладка там O(нового).
# Поэтому живая сверка едет В КАДРЕ, а не отдельным входом: у разбора она
# стоила суммы двух переписей, здесь — не стоит почти ничего.

LIVE_BUCKET_RU: dict[str, str] = {
    Bucket.BOTH: "видно и на плане, и в объёме",
    Bucket.PLAN_ONLY: ("нарисовано планом, тела НЕТ. Чаще всего это значит, что "
                       "нет снимка типов открытой модели: толщина стены и "
                       "диаметр трубы живут в ТИПЕ. Чинит ОПЕРАТОР — открыв "
                       "модель, — а не автор программы"),
    Bucket.SCENE_ONLY: ("тело есть, планом не нарисовано: обычно стояк "
                        "(в срез проецируется точкой) или элемент без этажа"),
    Bucket.NEITHER: ("операция написана, а элемента нет ни на одном экране: "
                     "либо она тела не создаёт вовсе (правка, датум, "
                     "помещение), либо его нечем построить"),
}


@dataclass
class _LiveTally:
    """Накопление корзин по кадрам сессии. Целая сцена обнуляет, хвост копит.

    ИДЕМПОТЕНТНОСТЬ ОБЯЗАТЕЛЬНА, И ЭТО НАЙДЕНО СВОИМ ЖЕ ЗАМЕРОМ. Замер цены
    кадра гонял ОДНУ И ТУ ЖЕ дельту семь раз подряд (чтобы взять минимум по
    времени), и накопление сложило её семь раз: 6 148 операций там, где их
    6 021. В жизни это не искусственный случай — панель повторяет запрос при
    ретрае, при потере ответа и при двух вкладках на одну сессию.

    Раздутая перепись СХОДИТСЯ САМА С СОБОЙ (корзины и знаменатель растут
    вместе), поэтому закон сходимости её не ловит — ровно та форма дефекта, за
    которой мы охотимся весь марафон. Лечится множеством уже посчитанных
    адресов: они уникальны в сессии по построению (`bundle_oid`), и повтор
    отличим от новизны точно, а не по догадке.
    """

    buckets: dict[str, int] = field(default_factory=dict)
    by_reason: dict[str, dict[str, int]] = field(default_factory=dict)
    ops: int = 0
    frames: int = 0
    #: Адреса, уже учтённые в корзинах. Цена — около 60 КБ на сессию из 6 000
    #: элементов; цена ошибки — перепись, которая врёт и сходится.
    counted: set = field(default_factory=set)
    repeats: int = 0


_LIVE: dict[tuple[str, str], _LiveTally] = {}
#: Сессий помним столько же, сколько витрина: два разных потолка на одну и ту
#: же сессию разъехались бы, и один из них молча перестал бы работать.
_LIVE_MAX = 8


def live_reset(key: tuple[str, str]) -> None:
    _LIVE[key] = _LiveTally()
    while len(_LIVE) > _LIVE_MAX:
        _LIVE.pop(next(iter(_LIVE)))


def live_frame(key: tuple[str, str], *, ops_by_id: dict, drawn: set,
               datums: set, bodied: set, refused: dict, no_body_ops: dict,
               whole: bool) -> dict[str, Any]:
    """Разложить элементы ОДНОГО кадра и вернуть НАКОПЛЕННУЮ сверку сессии.

    `whole=True` обнуляет накопление: целая сцена заменяет всё, что панель
    держала до неё, — тем же законом, что подпись показанного.

    ПРИЧИНА БЕРЁТСЯ ТОЛЬКО ТАМ, ГДЕ ОНА ЕСТЬ, и это разные источники:

      * у элемента, которому объём отказал, причина ПОИМЁННАЯ — её назвал
        построитель оболочек (`refused`);
      * у операции, не создавшей элемента вовсе, причина привязана к ИМЕНИ
        ОПЕРАЦИИ (`no_body` кейован именем), и это не догадка: «оп тела не
        создаёт» — свойство операции, а не её экземпляра. Так и подписано;
      * у элемента, которого не нарисовал ПЛАН, поимённой причины НЕТ:
        `PreviewCensus` группирует опущенное и хранит до пяти примеров.
        Приписать её по категории было бы догадкой, надетой на элемент.
    """
    if whole or key not in _LIVE:
        live_reset(key)
    tally = _LIVE[key]
    shown_by_plan = drawn | datums
    for element_id, op_name in ops_by_id.items():
        if element_id in tally.counted:
            # ПОВТОР НЕ СЧИТАЕТСЯ, НО НАЗЫВАЕТСЯ. Молча пропустить значило бы
            # спрятать факт, что панель переспрашивает одно и то же.
            tally.repeats += 1
            continue
        tally.counted.add(element_id)
        in_plan = element_id in shown_by_plan
        in_scene = element_id in bodied
        bucket = (Bucket.BOTH if in_plan and in_scene
                  else Bucket.PLAN_ONLY if in_plan
                  else Bucket.SCENE_ONLY if in_scene
                  else Bucket.NEITHER)
        tally.buckets[bucket] = tally.buckets.get(bucket, 0) + 1
        if bucket in (Bucket.PLAN_ONLY, Bucket.NEITHER):
            reason = refused.get(element_id)
            if reason is None and op_name in no_body_ops:
                reason = f"операция {op_name} тела не создаёт"
            tally.by_reason.setdefault(bucket, {})
            key_r = reason or "причина не названа ни одной переписью"
            tally.by_reason[bucket][key_r] = (
                tally.by_reason[bucket].get(key_r, 0) + 1)
    tally.ops = len(tally.counted)
    tally.frames += 1

    return {
        "schema": RECONCILE_SCHEMA,
        "source": "live",
        "available": True,
        "buckets": dict(sorted(tally.buckets.items())),
        "bucket_ru": LIVE_BUCKET_RU,
        "by_reason": {k: dict(sorted(v.items(), key=lambda kv: -kv[1])[:6])
                      for k, v in sorted(tally.by_reason.items())},
        "ops": tally.ops,
        "frames": tally.frames,
        "repeats": tally.repeats,
        "repeats_ru": ("адресов, пришедших повторно и НЕ посчитанных заново: "
                       "панель переспрашивает один и тот же срез"),
        # ЗАКОН СХОДИМОСТИ ТОТ ЖЕ. Операция, не попавшая ни в одну корзину, —
        # молчаливое выпадение, и сверка обязана его поймать, а не пережить.
        "balanced": sum(tally.buckets.values()) == tally.ops,
        "denominator_ru": ("знаменатель — ВСЕ написанные операции, а не только "
                           "те, у кого что-то получилось: иначе четвёртая "
                           "корзина пуста по построению"),
        "plan_reason_ru": ("причин плана поимённо нет: `PreviewCensus` "
                           "группирует опущенное и хранит до пяти примеров"),
    }
