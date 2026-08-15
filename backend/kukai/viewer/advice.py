"""ЧТО ДЕЛАТЬ — предложения разведения, доведённые до экрана целиком.

Вьюер показывает здание, показывает, чего мы о нём не знаем, показывает, что
внёс этот ход, и не даёт отправить в Revit то, чего инженер не видел. Не
хватало последнего звена: он показывал ПРОБЛЕМУ и не показывал ВЫХОД.

`kukai/clash/resolve.py` считает выход. Этот модуль его ЧИТАЕТ (в `clash` не
написано ни строки) и доводит до экрана ЧЕТЫРЕ части, ни одну из которых
нельзя выбросить.

════════════════════════════════════════════════════════════════════════════
ЗАМЕР 11.08.2026 — ДВА ЗДАНИЯ, ДВА ПРОТИВОПОЛОЖНЫХ ПРОФИЛЯ
════════════════════════════════════════════════════════════════════════════

| | `sob62_fas_r23_v19` | `snowdon_plumb_v4` |
|---|---|---|
| оболочек | 4 218 | 31 904 |
| находок (detect) | 27 041 за 1.6 с | 35 712 за 18.8 с |
| из них перекрытий | 19 239 | 35 633 |
| **цена одной пары** | **29.1 мс** | **372.4 мс** |
| рекомендации | `review` 286, `assembly_relation` 114 | `move` 300 |
| минимальность | `minimal_over_searched_directions` 100 % | **`separating_only` 100 %** |
| сертифицировано | 400 из 400 | 300 из 300 |
| ход законен | 289 из 400 | 300 из 300 |
| расстояние | медиана 100 мм, макс 1 517 | медиана 7.9 мм, макс 57.1 |

ДВА ВЫВОДА, И ОБА РЕШАЮТ ФОРМУ ЭТОГО МОДУЛЯ.

**ПЕРВЫЙ — ЦЕНА.** 19 239 × 29.1 мс = **9.3 минуты**; 35 633 × 372.4 мс =
**3.7 часа**. Это не «дорого для кадра», это дорого для одного нажатия.
Значит предложения считаются ТОЛЬКО по запросу, ТОЛЬКО для названной области
и ТОЛЬКО до названного потолка, а сцена честно говорит, что их не считали.
Граница та же, что уже дважды проведена: у живой сверки цена нулевая и она
едет в кадре, у сверки разбора цена в секунды и она отдельным входом, здесь
цена в часы — и она отдельный вход С ПОТОЛКОМ.

**ВТОРОЙ — МИНИМАЛЬНОСТЬ НЕ УКРАШЕНИЕ.** На инженерном здании ВСЕ 300 из 300
предложений имеют `separating_only`: точный путь неприменим для капсулы
против объединения кусков, ход РАЗВОДИТ и это проверено переносом, но
наименьшим он не объявлен даже вдоль своего направления. Показать «сдвиньте
трубу на 7.9 мм» без этой оговорки значит выдать оценку за оптимум — на 100 %
предложений этого здания. Поэтому `minimality` и его пояснение едут с КАЖДЫМ
предложением, а не в справке.

════════════════════════════════════════════════════════════════════════════
ЧЕТЫРЕ ЧАСТИ, И НИ ОДНА НЕ СВОДИТСЯ К ДРУГОЙ
════════════════════════════════════════════════════════════════════════════
1. **ЧИСЛО** — элемент, направление, расстояние. Даётся всегда, когда
   геометрия его даёт, независимо от классов сторон.
2. **РЕКОМЕНДАЦИЯ** — `move` | `review` | `verify_duplicate` |
   `assembly_relation`. Четыре РАЗНЫХ действия; подменить их одним словом
   значит сказать «подвиньте» там, где ответ «это узел, а не конфликт».
3. **МИНИМАЛЬНОСТЬ** — «наименьший из просмотренных направлений» против
   «разводит, но не наименьший». Едет вместе с числом направлений и их
   происхождением: `minimal_over_searched_directions` без знаменателя —
   слово без числа.
4. **СЕРТИФИЦИРОВАННОСТЬ** — постусловие проверено НАСТОЯЩИМ переносом, а не
   заявлено. Инженер, которому предлагают подвинуть колонну, вправе знать,
   проверяли ли предложение.

════════════════════════════════════════════════════════════════════════════
ОТКАЗ ПОСТРОИТЬ ПРЕДЛОЖЕНИЕ ОТЛИЧИМ ОТ «ДВИГАТЬ НЕ НАДО»
════════════════════════════════════════════════════════════════════════════
`resolve` возвращает два разных отказа, и склеить их нельзя:

  * `not_overlapping` — пара не пересекается. Двигать НЕ НАДО, это ответ;
  * `no_certified_direction` — пара пересекается, а разводящего хода мы не
    нашли. Это НАШЕ бессилие, а не свойство здания.

Первое — зелёное, второе — красное, и на экране они разными словами. Стрелка
не рисуется ни в одном из двух случаев: показывать выход, которого нет,
хуже, чем не показывать ничего.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ("ADVICE_SCHEMA", "COST_PER_PAIR_MS", "DEFAULT_LIMIT", "MAX_LIMIT",
           "REFUSAL_RU", "Advice", "advise_run", "unavailable")

ADVICE_SCHEMA = "kir-viewer-advice/1"

#: Измеренная цена одной пары, мс. Публикуется, чтобы потолок был обоснован
#: числом, а не вкусом.
#:
#: ДВА ЗАМЕРА НА ОДНОМ ЗДАНИИ, И ВТОРОЙ ОТМЕНИЛ ПЕРВЫЙ ПОТОЛОК. Случайная
#: выборка `snowdon_plumb_v4` дала 372.4 мс на пару, и потолок был поставлен
#: по ней. Но область выбирается ПО ГЛУБИНЕ (мелкое считать первым — значит
#: считать не то), а глубокие пары дороже: та же выборка, отсортированная по
#: глубине, дала **977.1 мс**. Выбирая самое важное, мы выбираем и самое
#: медленное — и потолок, посчитанный по среднему, промахнулся бы в 2.6 раза.
COST_PER_PAIR_MS = {
    "sob62_fas_r23_v19": 16.6,          # 750 пар, отсортированных по глубине
    "snowdon_plumb_v4": 977.1,          # 150 пар, отсортированных по глубине
}

#: Худшая измеренная цена. Потолок считается от НЕЁ, а не от средней: область
#: берётся по глубине, то есть заведомо из дорогого конца.
WORST_PAIR_MS = 977.1

#: Сколько секунд имеет право занять ОДНО НАЖАТИЕ. Больше — и кнопка
#: перестаёт быть кнопкой.
PRESS_BUDGET_S = 60.0

#: Потолок пар за один запрос. Не константа из головы: 60 с / 977.1 мс = 61.
DEFAULT_LIMIT = 25
MAX_LIMIT = int(PRESS_BUDGET_S * 1000.0 / WORST_PAIR_MS)

REFUSAL_RU: dict[str, str] = {
    # ДВИГАТЬ НЕ НАДО — это ОТВЕТ, а не бессилие.
    "not_overlapping": ("пара не пересекается: двигать не надо. Это ОТВЕТ, а "
                        "не отказ. Замер 11.08: все 180 отказов на двух "
                        "зданиях — этот, и все до одного пришли от КАСАНИЙ"),
    # НАШЕ БЕССИЛИЕ — пара пересекается, а хода мы не нашли.
    "no_certified_direction": ("пара ПЕРЕСЕКАЕТСЯ, но разводящего хода не "
                               "найдено ни для одной стороны: ни одно "
                               "просмотренное направление не прошло проверку "
                               "переносом. Это наше бессилие, а не свойство "
                               "здания. НА ЭТОМ КОРПУСЕ НЕ НАБЛЮДАЛСЯ НИ РАЗУ "
                               "(0 из 720 предложений), и различие держится "
                               "именно поэтому: пустая названная причина "
                               "отличима от несуществующей"),
}

#: Какие отказы означают «всё хорошо», а какие — «мы не смогли». Список
#: закрыт: новый отказ, не отнесённый ни к одной стороне, обязан быть замечен
#: тестом, а не уехать на экран нейтральным серым.
BENIGN_REFUSALS = frozenset({"not_overlapping"})


def unavailable(reason: str) -> dict[str, Any]:
    """Предложений нет — и СКАЗАНО ПОЧЕМУ. Пустой список и несчитанный список
    читаются одинаково только если молчать."""
    return {"schema": ADVICE_SCHEMA, "available": False, "reason": reason,
            "proposals": [], "considered": 0, "truncated": 0}


@dataclass
class Advice:
    run: str = ""
    proposals: list[dict] = field(default_factory=list)
    refusals: list[dict] = field(default_factory=list)
    overlaps_total: int = 0
    considered: int = 0
    truncated: int = 0
    by_recommendation: dict[str, int] = field(default_factory=dict)
    by_minimality: dict[str, int] = field(default_factory=dict)
    certified: int = 0
    legal: int = 0
    elapsed_ms: float = 0.0
    detect_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ADVICE_SCHEMA,
            "available": True,
            "run": self.run,
            "proposals": self.proposals,
            "refusals": self.refusals,
            "overlaps_total": self.overlaps_total,
            "considered": self.considered,
            # УСЕЧЕНИЕ НАЗЫВАЕТСЯ ЧИСЛОМ. Список из пятидесяти предложений и
            # список, где их пятьдесят из девятнадцати тысяч, — разные вещи,
            # и вторая без этой строки читается как первая.
            "truncated": self.truncated,
            "truncated_ru": (
                f"посчитаны {self.considered} пар из {self.overlaps_total}: "
                f"остальные {self.truncated} НЕ рассматривались — счёт одной "
                f"пары стоит 29–372 мс, и полное здание это часы"
                if self.truncated else ""),
            "by_recommendation": dict(sorted(self.by_recommendation.items())),
            "by_minimality": dict(sorted(self.by_minimality.items())),
            "certified": self.certified,
            "legal": self.legal,
            "certified_ru": ("ход проверен НАСТОЯЩИМ переносом и повторным "
                             "замером, а не заявлен"),
            "refusal_ru": REFUSAL_RU,
            "benign_refusals": sorted(BENIGN_REFUSALS),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "detect_ms": round(self.detect_ms, 1),
        }


def advise_run(run: str, *, limit: int = DEFAULT_LIMIT,
               element_id: str = "") -> Advice:
    """Предложения для разбора: область — либо один элемент, либо самые
    глубокие перекрытия. Считает ТОЛЬКО до потолка и говорит, сколько не считал.

    ОБЛАСТЬ ОБЯЗАТЕЛЬНА ПО ЦЕНЕ, А НЕ ПО ВКУСУ. 19 239 перекрытий фасада по
    29.1 мс — 9.3 минуты; 35 633 перекрытия инженерии по 372.4 мс — 3.7 часа.
    Поэтому либо «вокруг вот этого элемента», либо «самые глубокие сверху».
    """
    from kukai.clash import detect as D
    from kukai.clash import resolve as RS
    from kukai.clash import snapshot as S
    from kukai.viewer.scene import run_root

    started = time.perf_counter()
    base = run_root() / run
    if not base.exists():
        raise FileNotFoundError(f"разбора {run!r} нет в {run_root()}")
    limit = max(1, min(int(limit), MAX_LIMIT))

    snap = S.build_from_decompile(base)
    t0 = time.perf_counter()
    report = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    detect_ms = (time.perf_counter() - t0) * 1000.0

    by_id = {record.source_id: record for record in snap.records}
    overlaps = [f for f in (report.get("findings") or [])
                if f.get("hull_relation") == "overlap"]
    if element_id:
        overlaps = [f for f in overlaps
                    if str((f.get("a") or {}).get("source_element_id")) == element_id
                    or str((f.get("b") or {}).get("source_element_id")) == element_id]
    # СОРТИРОВКА ПО ГЛУБИНЕ, а не по адресу: если считать можно только часть,
    # считать надо самое глубокое. Порядок адресов выбрал бы область по
    # алфавиту, то есть ни по чему.
    overlaps.sort(key=lambda f: -float(f.get("hull_overlap_depth_mm") or 0.0))

    advice = Advice(run=run, overlaps_total=len(overlaps), detect_ms=detect_ms)
    chosen = overlaps[:limit]
    advice.considered = len(chosen)
    advice.truncated = len(overlaps) - len(chosen)

    hood = RS.Neighbourhood(snap.records)
    for finding in chosen:
        a = by_id.get(str((finding.get("a") or {}).get("source_element_id")))
        b = by_id.get(str((finding.get("b") or {}).get("source_element_id")))
        if a is None or b is None:
            continue
        proposal = RS.propose(
            a, b, hood=hood, pair_kind=finding.get("pair_kind") or "interference",
            finding_id=finding.get("finding_id"))
        payload = proposal.as_dict()
        payload["depth_mm"] = round(
            float(finding.get("hull_overlap_depth_mm") or 0.0), 1)
        payload["pair_class"] = finding.get("pair_class")
        if proposal.chosen is None:
            # СТРЕЛКА НЕ РИСУЕТСЯ. Показывать выход, которого нет, хуже, чем
            # не показывать ничего; поэтому отказ уезжает в СВОЙ список.
            payload["benign"] = proposal.refusal in BENIGN_REFUSALS
            payload["refusal_ru"] = REFUSAL_RU.get(
                proposal.refusal or "", "причина отказа не названа")
            advice.refusals.append(payload)
            continue
        # ЧЕЛОВЕЧЕСКАЯ СТРОКА БЕРЁТСЯ У ВЛАДЕЛЬЦА ПРАВИЛА, а не собирается
        # здесь: своя формулировка разошлась бы с `to_russian` на первом же
        # уточнении глагола, и разошлась бы молча.
        payload["ru"] = RS.to_russian(proposal)
        advice.proposals.append(payload)
        rec = proposal.recommendation
        advice.by_recommendation[rec] = advice.by_recommendation.get(rec, 0) + 1
        mini = proposal.chosen.minimality
        advice.by_minimality[mini] = advice.by_minimality.get(mini, 0) + 1
        advice.certified += int(bool(proposal.chosen.certified))
        advice.legal += int(bool(proposal.chosen.legal))

    advice.elapsed_ms = (time.perf_counter() - started) * 1000.0
    return advice
