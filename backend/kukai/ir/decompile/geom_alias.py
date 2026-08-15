"""АЛИАС ФОРМЫ ПО ТИПУ: кого спрашивать у Revit, а кому отдать чужой ответ.

ЗАЧЕМ. Склад форм и так content-addressed: одинаковая геометрия ложится под
один `geo_hash` и физически не дублируется (`geom_extract.GeometryStore`). Но
дедупликация происходит ПОСЛЕ моста — «the Python half deduplicates its bridge
payload offline». То есть экономится ХРАНЕНИЕ и не экономится СЪЁМ: чтобы
получить 268 различных форм башни K2, сегодня пришлось бы вытащить через мост
38 175 экземпляров.

Замысел «форма принадлежит типу» доехал до склада и не доехал до двери. Этот
модуль — дверь: он делит запрошенные элементы на тех, кого спросят, и тех, кто
получит форму соседа по типу.

🔴 ФОРМА ПРИНАДЛЕЖИТ ТИПУ НЕ ВСЕГДА, И ЭТО ИЗМЕРЕНО, А НЕ ДОПУЩЕНО.

Замер 15.08.2026 на `k2_ar_rd_v15` (35 943 экземпляра, 266 типов, порог 2 мм,
объявленный до замера): согласованы по габариту лишь 28.48 % экземпляров, и
раскол СТРУКТУРНЫЙ, а не случайный:

    двери           1743 из 2096     каталожное семейство — алиас законен
    сантехника      1422 из 1426     каталожное
    балки           1361 из 1426     каталожное
    мимбели           65 из 11 994   КРОИТСЯ ПО ЯЧЕЙКЕ — форма у ЭКЗЕМПЛЯРА
    панели витража   437 из 4 322    кроится
    телефоны          11 из 4 479

Поэтому представитель НИКОГДА не назначается на веру. Он назначается, а
остальные экземпляры того же типа СВЕРЯЮТСЯ по габариту; разошедшиеся
спрашиваются отдельно и попадают в отчёт под своим именем.

ГРАНИЦА ПРИБОРА, названная здесь, а не обнаруженная потом. Габарит —
СЛАБЫЙ представитель формы, и слаб он в одну сторону:

  * разные формы с одинаковым габаритом он НЕ различит — теоретическая дыра,
    против которой у нас нет дешёвого прибора;
  * одинаковые формы, повёрнутые на НЕПРЯМОЙ угол, он объявит разными.
    Сортировка размеров снимает повороты на 90° и зеркала, произвольный угол —
    нет. Поэтому доля алиасов, посчитанная габаритом, есть НИЖНЯЯ ГРАНИЦА
    экономии, а не её оценка.

Обе стороны асимметричны по цене, и умолчание выбрано по этой асимметрии:
**сомневаешься — СПРАШИВАЙ**. Лишний рейс стоит времени; чужая форма, выданная
за свою, есть молчаливо-неверный результат, а он запрещён по построению.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


def type_shapes_enabled() -> bool:
    """Ворота библиотеки форм по типу; по умолчанию ВЫКЛЮЧЕНО.

    ПОЧЕМУ ВЫКЛЮЧЕНО, хотя канал доказан живьём (15.08: 31 съём, 30 типов с
    формой, 425 экземпляров покрыто, 16 с). Конвейер объявляет цену прямо в
    коде — «Extracting full geometry for all L0 elements would waste the Revit
    budget» — и цена настоящая: каждый представитель это рейс к мосту. Флаг
    существует затем, чтобы эта цена была РЕШЕНИЕМ, а не побочным эффектом
    чужой правки.

    ЧЕСТНЫЙ СТАТУС НА 15.08: канал проверен ОТДЕЛЬНЫМ прибором на живой модели;
    ЧЕРЕЗ КОНВЕЙЕР он живьём не гонялся ни разу (в тот час Ревит перестал
    исполнять). Это ровно третье состояние флага, которое канон требует
    называть: не «включено», не «выключено», а «построено и не обкатано».
    """
    return os.getenv("KUKAI_IR_TYPE_SHAPES", "").strip().lower() in {
        "1", "true", "yes", "on",
    }

#: Допуск сравнения габаритов, мм. Объявлен ДО замера доли алиасов и совпадает
#: с порогом габарита, которым закрывалась цель «форма 1в1» (24 семейства из
#: 24). Число здесь ASSIGNED, а не выведено, и потому едет в отчёт вместе с
#: долей: читатель обязан видеть, при каком допуске она получена.
BBOX_TOLERANCE_MM = 2.0

#: Почему экземпляр спрашивается отдельно. Список ЗАКРЫТ и ПОЛОН ПО
#: ПОСТРОЕНИЮ: каждый элемент входа получает ровно одну метку, и `assert`
#: в `plan_geometry_asks` это держит. Новая причина обязана появиться здесь,
#: иначе она уедет в отчёт безымянной.
ASK_REASONS = (
    "representative",        # он и есть образец своего типа
    "type_unknown",          # тип не прочитан — алиасу не на чём стоять
    "bbox_unknown",          # габарита нет, сверить нечем
    "instance_driven",       # габарит разошёлся с образцом: форму гнёт экземпляр
    "singleton",             # тип в одном экземпляре: алиасить некому
)


@dataclass(frozen=True)
class GeometryAskPlan:
    """Кого спрашивать, кому отдать чужое, и почему — по каждому элементу."""

    #: id, которые уходят в `build_geometry_extract_cs`.
    ask: tuple[str, ...]
    #: элемент -> элемент-образец, чью форму он получит.
    alias: dict[str, str]
    #: элемент -> причина из `ASK_REASONS` (только для тех, кого спрашивают).
    reason: dict[str, str]
    #: сводка для квитанции; числа, а не прилагательные.
    stats: dict[str, Any] = field(default_factory=dict)

    def saved_calls(self) -> int:
        """Сколько рейсов к мосту сэкономлено. Ноль — законный ответ."""
        return len(self.alias)


def _dims(bbox_min: Any, bbox_max: Any) -> tuple[float, float, float] | None:
    """Размеры габарита, отсортированные. Сортировка — это и есть снятие
    поворотов на 90° и зеркал; произвольный угол ею не снимается (см. шапку)."""
    if not (isinstance(bbox_min, (list, tuple))
            and isinstance(bbox_max, (list, tuple))
            and len(bbox_min) == 3 and len(bbox_max) == 3):
        return None
    try:
        out = sorted(float(bbox_max[i]) - float(bbox_min[i]) for i in range(3))
    except (TypeError, ValueError):
        return None
    if any(v != v or v in (float("inf"), float("-inf")) for v in out):
        return None
    return (out[0], out[1], out[2])


def _same_shape(a: tuple[float, float, float],
                b: tuple[float, float, float],
                tolerance_mm: float) -> bool:
    return all(abs(a[i] - b[i]) <= tolerance_mm for i in range(3))


def plan_geometry_asks(
    elements: Iterable[Mapping[str, Any]],
    *,
    tolerance_mm: float = BBOX_TOLERANCE_MM,
) -> GeometryAskPlan:
    """Разложить элементы на «спросить» и «взять у образца».

    `elements` — записи с ключами `element_id`, `type_id` (может отсутствовать),
    `bbox_min_mm`, `bbox_max_mm`. Читаются ровно эти поля: модуль не ходит ни в
    Revit, ни на диск, поэтому проверяется целиком офлайн.

    ОБРАЗЕЦ ВЫБИРАЕТСЯ ДЕТЕРМИНИРОВАННО — наименьший id типа. Не украшение:
    недетерминированный выбор дал бы одному зданию разные `geo_hash` от
    прогона к прогону, и разность двух разборов (`kir_merkle`, дельта
    перестройки) показала бы правки там, где ничего не менялось.
    """
    rows: list[tuple[str, str | None, tuple[float, float, float] | None]] = []
    for el in elements:
        eid = el.get("element_id")
        if eid is None:
            continue
        rows.append((str(eid),
                     None if el.get("type_id") in (None, "")
                     else str(el.get("type_id")),
                     _dims(el.get("bbox_min_mm"), el.get("bbox_max_mm"))))

    by_type: dict[str, list[tuple[str, tuple[float, float, float] | None]]] = {}
    ask: list[str] = []
    reason: dict[str, str] = {}
    alias: dict[str, str] = {}

    for eid, tid, dims in rows:
        if tid is None:
            ask.append(eid)
            reason[eid] = "type_unknown"
            continue
        by_type.setdefault(tid, []).append((eid, dims))

    instance_driven = 0
    aliased_types = 0
    for tid, members in sorted(by_type.items()):
        members.sort(key=_id_order)
        if len(members) == 1:
            eid = members[0][0]
            ask.append(eid)
            reason[eid] = "singleton"
            continue
        head_eid, head_dims = members[0]
        ask.append(head_eid)
        reason[head_eid] = "representative"
        if head_dims is None:
            # Образец без габарита сверять нечем — тогда НИКТО не алиасится к
            # нему. Умолчание «сомневаешься — спрашивай», а не «поверим ему».
            for eid, _d in members[1:]:
                ask.append(eid)
                reason[eid] = "bbox_unknown"
            continue
        used = False
        for eid, dims in members[1:]:
            if dims is None:
                ask.append(eid)
                reason[eid] = "bbox_unknown"
            elif _same_shape(head_dims, dims, tolerance_mm):
                alias[eid] = head_eid
                used = True
            else:
                ask.append(eid)
                reason[eid] = "instance_driven"
                instance_driven += 1
        if used:
            aliased_types += 1

    total = len(rows)
    assert len(ask) + len(alias) == total, (
        "каждый элемент обязан быть либо спрошен, либо приписан к образцу")
    assert set(reason) == set(ask), "у каждого спрошенного своя причина"

    stats = {
        "elements": total,
        "types": len(by_type),
        "asked": len(ask),
        "aliased": len(alias),
        "aliased_types": aliased_types,
        "instance_driven": instance_driven,
        "tolerance_mm": tolerance_mm,
        # Доля — НИЖНЯЯ ГРАНИЦА: габарит объявляет разными одинаковые формы,
        # повёрнутые на непрямой угол. Имя поля обязано это нести, иначе
        # число прочтут как оценку.
        "alias_share_lower_bound": (
            round(100.0 * len(alias) / total, 2) if total else 0.0),
    }
    return GeometryAskPlan(tuple(ask), alias, reason, stats)


def _id_order(item: tuple[str, Any]) -> tuple[int, Any]:
    """Числовые id — по числу, прочие — по строке. Смешанная сортировка строк
    дала бы «10» < «9» и сделала бы выбор образца зависимым от разрядности."""
    eid = item[0]
    try:
        return (0, int(eid))
    except (TypeError, ValueError):
        return (1, eid)


def attach_aliased_geometry(index_rows: Sequence[Mapping[str, Any]],
                            plan: GeometryAskPlan) -> list[dict[str, Any]]:
    """Дописать строки индекса тем, кто получил форму образца.

    Вход — то, что вернул съём (по одной строке на СПРОШЕННЫЙ элемент, с
    `geo_hash` и `transform`). Выход — те же строки плюс строки алиасов.

    🔴 `transform` ОБРАЗЦА НЕ КОПИРУЕТСЯ. Он описывает положение ОБРАЗЦА в
    пространстве, и выдать его соседу значило бы поставить дверь туда, где
    стоит другая дверь. Алиас несёт форму и НЕ несёт положение: его `transform`
    остаётся пустым, а положение приходит оттуда же, откуда приходило всегда —
    из L0 самого экземпляра. Строка помечена `alias_of`, чтобы читатель
    отличал снятое от приписанного.
    """
    # 🔴 ПОЛЕ ЗАПИСИ — `element_id`, И ЭТО СПРОШЕНО У ЖИВОГО СЪЁМА, А НЕ
    # ПРЕДПОЛОЖЕНО. Первая редакция читала `source_element_id` — так поле
    # зовётся в индексе КОНВЕЙЕРА, и имя выглядело очевидным. Живой прогон
    # 15.08 дал НОЛЬ форм при НУЛЕ отказов: тихая пустота, которую видно
    # только счётчиком. `GeometryIndexRecord` несёт `element_id`.
    #
    # Старое имя принимается как запасное: индекс конвейера действительно
    # зовёт его так, и молча не найти строку — тот же дефект в другую сторону.
    def _row_id(row):
        return str(row.get("element_id")
                   if row.get("element_id") is not None
                   else row.get("source_element_id"))

    by_id = {_row_id(r): r for r in index_rows}
    out = [dict(r) for r in index_rows]
    for eid, head in plan.alias.items():
        source = by_id.get(str(head))
        if source is None:
            continue          # образец не снялся — алиас не выдаём молча
        row = dict(source)
        # Пишем В ТО ЖЕ ПОЛЕ, откуда прочитали: смешать два имени в одном
        # наборе строк значило бы отдать потребителю набор, половину которого
        # он адресует, а половину нет.
        if source.get("element_id") is not None:
            row["element_id"] = eid
        else:
            row["source_element_id"] = eid
        row["alias_of"] = str(head)
        row["transform"] = None
        out.append(row)
    return out


#: Тир съёма, который считается НАСТОЯЩЕЙ формой. `Gb` — тот же габаритный
#: ящик, добытый дороже, и складывать его с мешем в одну графу «формы» значит
#: объявить победой ровно то, на что жаловался владелец.
MESH_TIER = "Gm"


def build_type_shape_library(
    elements: Iterable[Mapping[str, Any]],
    index_rows: Sequence[Mapping[str, Any]],
    plan: GeometryAskPlan,
) -> dict[str, Any]:
    """`{type_id: geo_hash}` плюс числа, по которым это решение оценивают.

    Библиотека собирается ТОЛЬКО из представителей: одиночка и «личная форма»
    формы ТИПА не имеют по определению, и записать их сюда значило бы выдать
    форму одного экземпляра за форму всех.

    Тир каждой строки различается: `types_with_mesh` и `types_with_shape` —
    разные числа, и отчёт обязан нести оба.
    """
    type_of = {str(e.get("element_id")): str(e.get("type_id"))
               for e in elements if e.get("element_id") is not None
               and e.get("type_id") not in (None, "")}

    reps = {eid for eid in plan.ask
            if plan.reason.get(eid) == "representative"}

    shapes: dict[str, str] = {}
    mesh_types: set[str] = set()
    tiers: dict[str, int] = {}
    for row in index_rows:
        eid = str(row.get("element_id")
                  if row.get("element_id") is not None
                  else row.get("source_element_id"))
        if eid not in reps:
            continue
        geo_hash = row.get("geo_hash")
        type_id = type_of.get(eid)
        tier = row.get("tier")
        tier = str(getattr(tier, "value", tier) or "")
        tiers[tier] = tiers.get(tier, 0) + 1
        if not geo_hash or not type_id:
            continue
        shapes[type_id] = str(geo_hash)
        if tier == MESH_TIER:
            mesh_types.add(type_id)

    covered = sum(1 for e in elements
                  if str(e.get("type_id")) in shapes)
    covered_mesh = sum(1 for e in elements
                       if str(e.get("type_id")) in mesh_types)
    return {
        "schema": "type-shape-library/1",
        "type_shapes": shapes,
        "types_with_shape": len(shapes),
        "types_with_mesh": len(mesh_types),
        "instances_covered": covered,
        "instances_covered_by_mesh": covered_mesh,
        "tiers": tiers,
        "representatives_asked": len(reps),
        # То же имя, что в `plan.stats`: габарит объявляет разными одинаковые
        # формы, повёрнутые на непрямой угол, поэтому это НИЖНЯЯ граница.
        "alias_share_lower_bound": plan.stats.get("alias_share_lower_bound"),
    }
