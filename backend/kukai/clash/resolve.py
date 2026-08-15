"""ЧТО ДВИНУТЬ, КУДА И НА СКОЛЬКО — предложение, а не список пар.

Детектор говорит «эти двое пересекаются». Проектировщику этого мало: красное
он и так видит. Инструментом список становится тогда, когда каждая находка
называет ЭЛЕМЕНТ, НАПРАВЛЕНИЕ, РАССТОЯНИЕ и — обязательно — ЗАКОНЕН ли ход.

ПОЧЕМУ ЧИСЛО ДАЁТСЯ ВСЕГДА, А РЕКОМЕНДАЦИЯ — НЕ ВСЕГДА. Первая версия этого
модуля отказывала целиком, как только обе стороны оказывались конструкцией
(`both_immovable`), и на живом здании это дало 3 346 отказов из 3 348
(`sob62_r23_v5`) и 4 000 из 4 000 (`snowdon_plumb_v5`) — то есть инструмент
молчал ровно там, где его спрашивали. Отказ был вежливым, но бесполезным:
«стена A входит в стену B на 120 мм, и чтобы выйти, ей нужно 120 мм по +X» —
факт о геометрии, и прятать его не за что. Решает, ИСПОЛНЯТЬ ли ход, человек;
дело модуля — не подменять это решение и не лишать его чисел.

Поэтому здесь две РАЗНЫЕ оси, и они никогда не складываются в одну:

  ЧИСЛО         — элемент, направление, расстояние, законность. Есть всегда,
                  когда геометрия его даёт, независимо от классов сторон.
  РЕКОМЕНДАЦИЯ  — `move` | `review` | `verify_duplicate` | `assembly_relation`.
                  Говорит, что с числом делать, и никогда не притворяется
                  сильнее, чем данные позволяют.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ `geom.certified_separating_translation`. Та функция
обещает ровно одно и обещание держит: после переноса пара разведена. Но она
(а) двигает всегда сторону A, выбранную по ПОРЯДКУ АДРЕСОВ, а не по смыслу,
(б) минимальности не обещает и не даёт — её собственная строка документации
говорит это прямо, (в) про третьи тела не знает ничего. Все три дыры закрыты
здесь, и ни одна не закрыта угадыванием.

СКОЛЬКО СТОИЛА ДЫРА (б) — ЗАМЕР, А НЕ ОЦЕНКА. Инструмент: 600 настоящих
находок-перекрытий `sob62_r23_v5`, разбор 10.08.2026, отношение длины хода
`geom.certified_separating_translation` к длине `minimal_exit` на той же паре:

    медиана   5.892x
    p90      56.667x
    максимум 112 066.5x

Сто тысяч раз — это не «неоптимально», это другое указание: там, где трубе
хватает восьми миллиметров вбок, прежний вектор уводил её на десятки метров
вверх. Число записано ЗДЕСЬ и продублировано ссылкой в самой
`certified_separating_translation`, потому что письмо кончается вместе с
сессией, а код остаётся.

ЧТО ИЗМЕНИЛА ВОЛНА DECOMPOSE (11.08.2026). Появление невыпуклой оболочки
`geom.PrismSet` убило обоснование, на котором стоял `minimal_exit`: у
объединения выпуклых кусков множество тех сдвигов, при которых пара
пересекается, перестаёт быть отрезком. Замер до правки: плита с ПРОЁМОМ
против бруска, 400 пересекающихся пар — у 92 из них (23.0 %) бисекция
выдавала ход длиннее наименьшего, в худшем случае в 6.79 раза. Минимальность
ВОССТАНОВЛЕНА точным вычислением отрезков по парам кусков, а не снята.

И ОДНО, ЧЕГО ЗДЕСЬ НИКОГДА НЕ БЫЛО, ХОТЯ ЗВУЧАЛО ТАК, БУДТО БЫЛО. Слово
«наименьший» относилось и относится к КОНЕЧНОМУ набору направлений
(`_directions`), а не ко всем направлениям пространства. Замер против плотной
сетки из 900 направлений сферы: для пары призма-призма набор ПОЛОН (0
расхождений на 120 парах — обе призмы выдавлены вдоль одной оси, поэтому
нормалей граней достаточно), для пары капсула-призма НЕ полон (60 расхождений
из 120, ход до 1.17 раза длиннее наименьшего). Вторая половина была верна и до
этой волны — её просто никто не измерял. Теперь она едет в самой находке
полем `Move.minimality`, а не в комментарии к коду.

ТРИ ЗАКОНА, НА КОТОРЫХ СТОИТ МОДУЛЬ.

1. КОНСТРУКЦИЯ НЕ УСТУПАЕТ ИНЖЕНЕРИИ. Труба обходит балку; балка трубу — нет.
   Это не вкус и не норма, а порядок сборки: несущее ставится по расчёту, сети
   прокладываются по месту.

2. МЕНЬШЕЕ СЕЧЕНИЕ УСТУПАЕТ БОЛЬШЕМУ. Между собой сети ранжируются по ПЛОЩАДИ
   СЕЧЕНИЯ из `section_radius_mm` — из того самого числа, которым обоснована
   капсула. Где числа нет, сравнивать нечем, и порядок решается классом; это
   сказано полем `rank_basis`, а не спрятано в умолчание.

3. МИНИМАЛЬНОСТЬ ДОКАЗЫВАЕТСЯ, А НЕ ОБЪЯВЛЯЕТСЯ. Множество
   `{t : (A + t·d) ∩ B ≠ ∅}` для ВЫПУКЛЫХ тел есть ОТРЕЗОК, поэтому наименьшее
   `t`, выводящее пару, находится бисекцией и не требует веры. Оболочки модуля
   выпуклы все три, так что условие выполнено по построению, а не «обычно».
   Найденный ход ПРОВЕРЯЕТСЯ постусловием `geom.separates` — тем же, которым
   проверяет себя сам `geom`.

ЧЕГО ЗДЕСЬ НЕТ. Строительного кодекса, уклонов, зон обслуживания, правил
подвески. Их в данных нет, а выдумать их значило бы подписать ось, которую
никто не читал.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from kukai.clash import geom as G
from kukai.clash import hulls as H

__all__ = (
    "RESOLVE_SCHEMA",
    "RECOMMENDATIONS",
    "IMMOVABLE",
    "MOVE_CLASS",
    "RIDES_WITH_RUN",
    "ASSEMBLY_PAIRS",
    "LEGALITY_BLOCKERS",
    "Move",
    "Proposal",
    "Neighbourhood",
    "mobility_of",
    "minimal_exit",
    "exit_is_exact",
    "MINIMALITY",
    "MINIMALITY_NOTE",
    "MAX_EXIT_PIECE_PAIRS",
    "propose",
    "to_russian",
)

RESOLVE_SCHEMA = "kir-clash-resolution/2"

#: Что делать с числом. Закрытый список: рекомендация вне его — та самая
#: неподписанная ось, ради которой всё это писалось.
RECOMMENDATIONS: dict[str, str] = {
    "move": "исполняйте: сторона, которая уступает, определена порядком сборки",
    "review": "решает человек: обе стороны — конструкция, и её положение "
              "назначено расчётом, а не этим отчётом",
    "verify_duplicate": "геометрия похожа на дубликат, но удаление запрещено "
                        "до отдельного доказательства семантической и "
                        "dependency-эквивалентности",
    "assembly_relation": "это УЗЕЛ, а не ошибка: дверь в стене, панель в "
                         "витраже. Число дано для проверки, ход не назначается",
}


# ═════════════════════════════════════════════════════════════ 1. КТО УСТУПАЕТ

#: Метки `hulls.KIND_TABLE`, которые не двигаются по отчёту о геометрии.
IMMOVABLE = frozenset({
    "wall", "floor", "roof", "column", "beam", "foundation",
    "curtain_panel", "mullion", "curtain_system", "stairs", "ramp",
    "ceiling", "truss", "door", "window", "railing",
})

#: Класс подвижности: чем БОЛЬШЕ число, тем охотнее элемент уступает.
MOVE_CLASS: dict[str, int] = {
    "duct": 1, "duct_insulation": 1, "duct_lining": 1,
    "tray": 2,
    "pipe": 3, "pipe_insulation": 3,
    "conduit": 4,
}

#: Едут ЗА своим участком трассы, а не сами по себе: предлагать двигать
#: тройник отдельно от трубы значит предлагать разрыв сети.
RIDES_WITH_RUN = frozenset({
    "pipe_fitting", "duct_fitting", "tray_fitting", "conduit_fitting",
    "pipe_accessory", "duct_accessory", "duct_terminal", "sprinkler",
})

#: Пары меток, пересечение которых есть СПОСОБ СБОРКИ, а не конфликт. Список
#: закрыт и содержит только то, что проектировщик подтвердит не открывая норм:
#: дверь живёт В стене, панель и импост — В витраже, ограждение стоит НА
#: лестнице. Ход тут не назначается, но число публикуется: узел, разошедшийся
#: на полметра, — уже не узел.
ASSEMBLY_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"door", "wall"}),
    frozenset({"window", "wall"}),
    frozenset({"door", "curtain_panel"}),
    frozenset({"window", "curtain_panel"}),
    frozenset({"mullion", "curtain_panel"}),
    frozenset({"mullion", "curtain_system"}),
    frozenset({"curtain_panel", "curtain_system"}),
    frozenset({"mullion", "wall"}),
    frozenset({"curtain_panel", "wall"}),
    frozenset({"railing", "stairs"}),
    frozenset({"railing", "floor"}),
    frozenset({"stairs", "floor"}),
})

#: Названные причины, по которым ход НЕЗАКОНЕН. Список закрыт: ход без
#: приговора — то же молчание, от которого модуль и лечится.
LEGALITY_BLOCKERS: dict[str, str] = {
    "hits_third_body": "после переноса элемент входит в ТРЕТЬЕ тело, с "
                       "которым до переноса не пересекался",
    "leaves_level_band": "перенос выводит элемент за пределы его собственного "
                         "этажа",
    "exceeds_budget": "перенос больше бюджета: это перекладка участка, а не "
                      "правка примыкания",
    "uncertified": "постусловие `geom.separates` не подтвердило разведение",
}

#: Бюджет хода. За пределами собственного габарита элемента перенос перестаёт
#: быть правкой примыкания и становится перекладкой, которую по одному отчёту
#: о геометрии назначать нельзя.
BUDGET_FACTOR = 3.0
BUDGET_FLOOR_MM = 300.0
MAX_CELLS_PER_HULL = 512


def mobility_of(rec: H.HullRecord) -> tuple[int, float, str]:
    """(класс подвижности, площадь сечения, чем решено). Больше — подвижнее."""
    label = rec.label or ""
    if label in RIDES_WITH_RUN:
        return (0, 0.0, "rides_with_run")
    cls = MOVE_CLASS.get(label)
    if cls is None:
        return (0, 0.0, "immovable" if label in IMMOVABLE else "label_outside_table")
    r = rec.section_radius_mm
    if isinstance(r, (int, float)) and math.isfinite(r) and r > 0:
        return (cls, math.pi * float(r) * float(r), "section_radius_mm")
    return (cls, 0.0, "class_only")


def _order(a: H.HullRecord, b: H.HullRecord) -> tuple[H.HullRecord, H.HullRecord]:
    """(кто уступает, кто стоит). При равенстве решает адрес — детерминизм."""
    ca, aa, _ = mobility_of(a)
    cb, ab, _ = mobility_of(b)
    if ca != cb:
        return (a, b) if ca > cb else (b, a)
    if aa != ab:
        return (a, b) if aa < ab else (b, a)
    return (a, b) if a.source_id <= b.source_id else (b, a)


def _recommendation(a: H.HullRecord, b: H.HullRecord, pair_kind: str) -> str:
    if pair_kind == "coincident_duplicate":
        # Geometry answers only whether the occupied bodies coincide.  It says
        # nothing about phases, design options, systems, groups, ownership or
        # dependants.  Those are exactly the facts that decide whether either
        # BIM element may be deleted.  Keep the duplicate class visible, but
        # never mint a destructive recommendation from this geometry-only API.
        return "verify_duplicate"
    if frozenset({a.label or "", b.label or ""}) in ASSEMBLY_PAIRS:
        return "assembly_relation"
    ca, _, _ = mobility_of(a)
    cb, _, _ = mobility_of(b)
    if ca == 0 and cb == 0:
        return "review"
    return "move"


# ═════════════════════════════════════ 2. НАИМЕНЬШИЙ ХОД ВДОЛЬ НАПРАВЛЕНИЯ

def _unit(v: Sequence[float]) -> tuple[float, float, float] | None:
    L = math.sqrt(sum(c * c for c in v))
    if L <= G.EPS_MM:
        return None
    return (v[0] / L, v[1] / L, v[2] / L)


def _span(h: G.Hull) -> float:
    lo, hi = G.hull_bounds(h)
    return max(hi[k] - lo[k] for k in range(3)) or 1.0


#: Потолок на число пар кусков в одном поиске выхода. Точный путь стоит
#: O(m*n*рёбра), и у пары объединений это единственная величина, способная
#: вырасти неограниченно. За потолком — НАЗВАННЫЙ откат в бисекцию с пометкой
#: `separating_only`, а не тихое огрубление: молчаливая деградация здесь
#: неотличима от ответа. Замер 11.08.2026 по корпусу: медиана числа кусков
#: подошвы 27, максимум 63, худшая пара объединений даёт 63*63 = 3 969 пар —
#: потолок 4 096 её пропускает, а вырожденный контур с сотнями кусков нет.
MAX_EXIT_PIECE_PAIRS = 4096

#: КАК ПОЛУЧЕН опубликованный ход. Ось отдельная от `certified`: «перенос
#: разводит» и «перенос наименьший» — разные утверждения, и склеивать их в
#: одно поле значило бы повторить дефект, снятый ревью №14.
MINIMALITY = (
    #: Вдоль КАЖДОГО просмотренного направления `t` вычислен точно (правый
    #: конец компоненты нуля), а не нащупан. Минимум взят по КОНЕЧНОМУ набору
    #: направлений — глобальным минимумом по пространству он не является.
    "minimal_over_searched_directions",
    #: Точный путь неприменим (капсула против объединения либо потолок пар
    #: кусков). Ход РАЗВОДИТ, и это проверено переносом, но наименьшим он не
    #: обязан быть даже вдоль своего направления.
    "separating_only",
)


#: Что означает каждое значение `Move.minimality` — в самом отчёте, а не в
#: комментарии к коду. Читатель отчёта до кода не доходит, а разница между
#: «наименьший из просмотренных» и «наименьший вообще» решает, доверять ли
#: числу как проектному решению.
MINIMALITY_NOTE: dict[str, str] = {
    "minimal_over_searched_directions": (
        "вдоль КАЖДОГО просмотренного направления величина хода вычислена "
        "ТОЧНО (правый конец компоненты нуля в замкнутой форме, а не "
        "бисекцией), и проверена переносом. Минимум взят по КОНЕЧНОМУ набору "
        "направлений: оси, нормали граней всех кусков обеих оболочек и "
        "сертифицированный ход geom. Глобальным минимумом по всем "
        "направлениям пространства это НЕ является — замер 11.08.2026: для "
        "пары призма-призма набор полон (0 расхождений на 120 парах против "
        "сетки из 900 направлений), для пары капсула-призма НЕ полон "
        "(60 расхождений из 120, до 1.17 раза длиннее)."),
    "separating_only": (
        "ход РАЗВОДИТ пару, и это проверено переносом, но наименьшим он не "
        "объявлен даже вдоль своего направления: точный путь неприменим "
        "(капсула против объединения кусков либо превышен потолок "
        "MAX_EXIT_PIECE_PAIRS), и величина получена бисекцией, которая у "
        "невыпуклого тела сходится к концу СВОЕЙ компоненты."),
}


def _shift_interval(c: float, lo_a: float, hi_a: float,
                    lo_b: float, hi_b: float) -> tuple[float, float] | None:
    """Множество `t`, при которых отрезок `[lo_a, hi_a]`, сдвинутый на `t*c`,
    пересекает `[lo_b, hi_b]`. Отрезок либо пусто.

    Условие пересечения двух отрезков ЛИНЕЙНО по `t`, поэтому решается точно:
    `lo_a + t*c <= hi_b` и `lo_b <= hi_a + t*c`. При `c = 0` сдвига вдоль этой
    оси нет вовсе, и ответ — либо «всегда», либо «никогда».
    """
    if c == 0.0:
        return (-math.inf, math.inf) if (lo_a <= hi_b and lo_b <= hi_a) else None
    t1 = (hi_b - lo_a) / c
    t2 = (lo_b - hi_a) / c
    return (t1, t2) if t1 <= t2 else (t2, t1)


def _piece_exit_interval(fa, za, fb, zb, u) -> tuple[float, float] | None:
    """Множество `t`, при которых ПАРА ВЫПУКЛЫХ ПРИЗМ пересекается. ТОЧНО.

    Призма есть декартово произведение выпуклого многоугольника на отрезок по
    тем же осям, поэтому условие пересечения распадается на два независимых:
    по XY и по Z. Для XY по теореме о разделяющей оси у ВЫПУКЛЫХ многоугольников
    достаточно нормалей рёбер обоих. Вдоль каждой оси условие линейно по `t` и
    даёт отрезок; искомое множество — их пересечение, то есть тоже отрезок.

    Это строго лучше бисекции, которую предполагал план волны: ответ ТОЧЕН, а
    не сходится за `iters` шагов, стоимость фиксирована, и число итераций
    перестаёт влиять на публикуемую величину.
    """
    lo, hi = -math.inf, math.inf
    iv = _shift_interval(u[2], za[0], za[1], zb[0], zb[1])
    if iv is None:
        return None
    lo, hi = max(lo, iv[0]), min(hi, iv[1])
    axes = G._poly_axes(fa) + G._poly_axes(fb)
    if not axes:
        axes = [(1.0, 0.0), (0.0, 1.0)]
    for n in axes:
        amin, amax = G._project(fa, n)
        bmin, bmax = G._project(fb, n)
        iv = _shift_interval(u[0] * n[0] + u[1] * n[1], amin, amax, bmin, bmax)
        if iv is None:
            return None
        lo, hi = max(lo, iv[0]), min(hi, iv[1])
        if lo > hi:
            return None
    return (lo, hi) if lo <= hi else None


def _exact_exit_candidates(mover: G.Hull, fixed: G.Hull,
                           u: tuple[float, float, float]) -> list[float] | None:
    """Правые концы отрезков пересечения по всем парам кусков. `None` — нельзя.

    Наименьший выход обязан быть ПРАВЫМ КОНЦОМ одного из этих отрезков:
    объединение отрезков имеет границу только в их концах, а точная верхняя
    грань компоненты, содержащей ноль, — один из правых концов. Поэтому
    кандидаты перебираются ПО ВОЗРАСТАНИЮ, а решает ПРОВЕРКА ПЕРЕНОСОМ на
    настоящих телах: сливать отрезки в компоненты руками не надо, и ошибка
    слияния поэтому невозможна в принципе.
    """
    fa, fb = G.footprint_pieces(mover), G.footprint_pieces(fixed)
    za, zb = G.z_span(mover), G.z_span(fixed)
    if fa is None or fb is None or za is None or zb is None:
        return None                      # капсула: точного пути пока нет
    if len(fa) * len(fb) > MAX_EXIT_PIECE_PAIRS:
        return None
    out: list[float] = []
    for pa in fa:
        for pb in fb:
            iv = _piece_exit_interval(pa, za, pb, zb, u)
            if iv is None:
                continue
            if math.isinf(iv[1]):
                return None              # вдоль этого направления выхода нет
            if iv[1] >= 0.0:
                out.append(iv[1])
    return sorted(set(out))


def _bisect_exit(mover, fixed, u, iters, ceiling):
    """Прежняя бисекция. Ответ ПРОВЕРЕН переносом, минимальность не обещана."""
    reach = _span(mover) + _span(fixed)
    hi = max(1.0, reach * 0.05)
    ok = False
    for _ in range(40):
        if G.separates(mover, fixed, tuple(c * hi for c in u)):
            ok = True
            break
        if ceiling is not None and hi > ceiling:
            return None
        hi *= 2.0
        if hi > reach * 8.0:
            return None
    if not ok:
        return None
    lo = 0.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if G.separates(mover, fixed, tuple(c * mid for c in u)):
            hi = mid
        else:
            lo = mid
    return hi


def minimal_exit(mover: G.Hull, fixed: G.Hull, d: Sequence[float], *,
                 iters: int = 50, ceiling: float | None = None) -> float | None:
    """Наименьшее `t >= 0`, при котором `mover + t*d` разведён с `fixed`.

    ПРЕЖНЕЕ ОБОСНОВАНИЕ БЫЛО ВЕРНЫМ И ПЕРЕСТАЛО БЫТЬ ПРИМЕНИМЫМ. Оно звучало
    так: «для выпуклых тел множество тех `t`, при которых пара пересекается,
    есть ОТРЕЗОК; все три оболочки модуля выпуклы, поэтому бисекция сходится к
    его правому концу». Первая половина верна (это проекция на `d` выпуклой
    разности Минковского), вторая умерла вместе с появлением `geom.PrismSet`:
    у ОБЪЕДИНЕНИЯ кусков множество распадается на объединение до `m*n`
    отрезков С ПРОМЕЖУТКАМИ. Вилка `[0, hi]` способна накрыть промежуток
    целиком, и тогда бисекция сходится к правому концу ЧУЖОЙ компоненты, то
    есть к ходу ДЛИННЕЕ наименьшего.

    ЗАМЕР, СДЕЛАННЫЙ ДО ПРАВКИ (11.08.2026, `w1_exit_probe.py`): плита с
    ПРОЁМОМ против бруска, 400 пересекающихся пар — у 92 из них (23.0 %)
    бисекция выдавала ход длиннее наименьшего, в худшем случае в 6.79 раза.
    Труба выходит В ПРОЁМ задолго до того, как покинет плиту, а вилка
    бисекции накрывала проём целиком.

    Минимальность здесь ВОССТАНОВЛЕНА, а не снята: у призменного семейства
    каждый отрезок считается ТОЧНО в замкнутой форме (`_piece_exit_interval`),
    а ответом служит наименьший из правых концов, ВЫДЕРЖАВШИЙ проверку
    переносом. Проверка обязательна — она превращает рассуждение о
    компонентах в предъявленный факт.

    Что НЕ обещано и почему — см. `MINIMALITY`: минимум берётся по КОНЕЧНОМУ
    набору направлений (`_directions`), и глобальным минимумом по всем
    направлениям пространства он не является.
    """
    u = _unit(d)
    if u is None:
        return None
    if G.separates(mover, fixed, (0.0, 0.0, 0.0)):
        return 0.0
    cands = _exact_exit_candidates(mover, fixed, u)
    if cands is not None:
        for t in cands:
            if ceiling is not None and t > ceiling:
                return None              # список отсортирован: дальше только хуже
            if G.separates(mover, fixed, tuple(c * t for c in u)):
                return t
        # Ни один кандидат не развёл — модель множества разошлась с геометрией.
        # Молчать нельзя, выдумывать тоже: уходим в бисекцию, которая свой
        # ответ проверяет переносом.
    return _bisect_exit(mover, fixed, u, iters, ceiling)


def exit_is_exact(mover: G.Hull, fixed: G.Hull) -> bool:
    """Доказуема ли МИНИМАЛЬНОСТЬ вдоль направления для этой пары оболочек."""
    fa, fb = G.footprint_pieces(mover), G.footprint_pieces(fixed)
    if fa is None or fb is None:
        return False
    return len(fa) * len(fb) <= MAX_EXIT_PIECE_PAIRS


def _directions(mover: G.Hull, fixed: G.Hull) -> list[tuple[float, float, float]]:
    """Направления-кандидаты. Побеждает НАИМЕНЬШИЙ ход, а не первый найденный.

    ПОЧЕМУ НОРМАЛИ БЕРУТСЯ СО ВСЕХ КУСКОВ. Прежний код спрашивал их через
    `isinstance(pf, G.Prism)`, поэтому `PrismSet` не давал НИ ОДНОЙ нормали и
    оставался с шестью осями координат. У пола, разложенного на 27 кусков, это
    выбрасывало все настоящие направления выхода — те самые, вдоль которых
    выход и оказывается коротким.

    ЧЕГО ЭТОТ НАБОР НЕ ДАЁТ, И ЭТО ИЗМЕРЕНО, А НЕ ПРЕДПОЛОЖЕНО. Для двух
    выпуклых тел истинно наименьший перенос идёт по нормали грани разности
    Минковского, а её грани порождаются гранями слагаемых И ВЕКТОРНЫМИ
    ПРОИЗВЕДЕНИЯМИ ПАР РЁБЕР. Замер 11.08.2026 (`w1_exit_probe.py`), минимум по
    этому набору против плотной сетки из 900 направлений сферы:

      * призма против призмы — 120 пересекающихся пар, РАСХОЖДЕНИЙ НОЛЬ.
        И это не везение: обе призмы выдавлены вдоль ОДНОЙ оси Z, поэтому их
        разность Минковского — снова призма вдоль Z, а её грани суть нормали
        рёбер подошв плюс плюс-минус Z. Набор для этого случая ПОЛОН;
      * капсула против призмы — 120 пар, РАСХОЖДЕНИЙ 60 (50.0 %), ход длиннее
        наименьшего до 1.17 раза. У капсулы «граней» нет вовсе, и ближайшая
        точка сплошь и рядом лежит на скруглении.

    Второй пункт — не дефект этой волны, он был здесь и до неё; волна лишь
    предъявила его числом. Поэтому `Move.minimality` называет вещь своим
    именем (`minimal_over_searched_directions`), а `directions_searched`
    публикует знаменатель.
    """
    out: list[tuple[float, float, float]] = [
        (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)]
    seen = set(out)

    def offer(v):
        u = _unit(v)
        if u is not None:
            # Округление до 9 знаков — не косметика: у пола в 27 кусков сотни
            # почти совпавших нормалей, и без склейки набор растёт вместе с
            # разбивкой, а вместе с ним и стоимость поиска.
            key = tuple(round(c, 9) for c in u)
            if key not in seen:
                seen.add(key)
                out.append(u)

    for pr in G._as_prisms(fixed):
        for n, _d in G._halfspaces(pr):
            offer(n)
    for pr in G._as_prisms(mover):
        for n, _d in G._halfspaces(pr):
            offer((-n[0], -n[1], -n[2]))
    v = G.certified_separating_translation(mover, fixed)
    if v is not None:
        offer(v)
    return out

# ═════════════════════════════════════════════════════════ 3. ЗАКОНЕН ЛИ ХОД

@dataclass(frozen=True)
class Move:
    element_id: str
    label: str
    category: str
    direction: tuple[float, float, float]
    distance_mm: float
    vector_mm: tuple[float, float, float]
    #: Постусловие `geom.separates` проверено ЗДЕСЬ, а не обещано.
    certified: bool
    legal: bool
    blockers: tuple[str, ...] = ()
    hits: tuple[str, ...] = ()
    rank_basis: str = ""
    #: НАСКОЛЬКО силён этот ход как МИНИМУМ. Ось отдельная от `certified`, и
    #: разделены они потому, что склейка «разводит» с «наименьший» — ровно тот
    #: дефект, который ревью №14 снимало у `verdict`/`hull_grade`. Значения —
    #: `MINIMALITY`.
    minimality: str = "separating_only"
    #: Знаменатель к слову «наименьший»: сколько направлений просмотрено.
    #: Без него `minimal_over_searched_directions` — слово без числа.
    directions_searched: int = 0
    #: Откуда взяты эти направления. Читатель обязан видеть, что набор
    #: КОНЕЧЕН и чем именно он порождён.
    direction_basis: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        def r(x):
            return G._norm_zero(round(float(x), 3))
        return {"element_id": self.element_id, "label": self.label,
                "category": self.category,
                "direction": [r(c) for c in self.direction],
                "distance_mm": r(self.distance_mm),
                "vector_mm": [r(c) for c in self.vector_mm],
                "certified": self.certified, "legal": self.legal,
                "blockers": list(self.blockers), "hits": list(self.hits),
                "rank_basis": self.rank_basis,
                "minimality": self.minimality,
                "minimality_note": MINIMALITY_NOTE.get(self.minimality, ""),
                "directions_searched": self.directions_searched,
                "direction_basis": list(self.direction_basis)}


@dataclass(frozen=True)
class Proposal:
    finding_id: str
    recommendation: str
    chosen: Move | None
    alternative: Move | None = None
    refusal: str | None = None

    def as_dict(self) -> dict:
        return {"schema": RESOLVE_SCHEMA,
                "finding_id": self.finding_id,
                "recommendation": self.recommendation,
                "recommendation_note": RECOMMENDATIONS.get(self.recommendation, ""),
                "chosen": None if self.chosen is None else self.chosen.as_dict(),
                "alternative": (None if self.alternative is None
                                else self.alternative.as_dict()),
                "refusal": self.refusal}


class Neighbourhood:
    """Кто ещё стоит рядом — чтобы ход не загонял элемент в третье тело."""

    def __init__(self, records: Sequence[H.HullRecord], cell: float | None = None):
        self.records = list(records)
        spans = sorted(max(hi[k] - lo[k] for k in range(3))
                       for lo, hi in (r.bounds() for r in self.records))
        med = spans[len(spans) // 2] if spans else 1000.0
        self.cell = cell or max(2.0 * med, 1.0)
        self.buckets: dict[tuple[int, int, int], list[int]] = {}
        self.giants: list[int] = []
        for idx, r in enumerate(self.records):
            lo, hi = r.bounds()
            i0 = [math.floor(lo[k] / self.cell) for k in range(3)]
            i1 = [math.floor(hi[k] / self.cell) for k in range(3)]
            n = 1
            for k in range(3):
                n *= (i1[k] - i0[k] + 1)
            if n > MAX_CELLS_PER_HULL:
                self.giants.append(idx)
                continue
            for x in range(i0[0], i1[0] + 1):
                for y in range(i0[1], i1[1] + 1):
                    for z in range(i0[2], i1[2] + 1):
                        self.buckets.setdefault((x, y, z), []).append(idx)

    def near(self, lo, hi) -> set[int]:
        i0 = [math.floor(lo[k] / self.cell) for k in range(3)]
        i1 = [math.floor(hi[k] / self.cell) for k in range(3)]
        n = 1
        for k in range(3):
            n *= (i1[k] - i0[k] + 1)
        if n > MAX_CELLS_PER_HULL:
            return set(range(len(self.records)))
        out: set[int] = set(self.giants)
        for x in range(i0[0], i1[0] + 1):
            for y in range(i0[1], i1[1] + 1):
                for z in range(i0[2], i1[2] + 1):
                    out.update(self.buckets.get((x, y, z), ()))
        return out


def _level_band(rec: H.HullRecord, levels: Mapping[str, float] | None
                ) -> tuple[float, float] | None:
    """Полоса собственного этажа. `None` — нечем судить, и это НЕ приговор."""
    if not levels or rec.level_id is None:
        return None
    key = str(rec.level_id)
    if key not in levels:
        return None
    base = float(levels[key])
    above = sorted(float(e) for e in levels.values() if float(e) > base + 1.0)
    return base, (above[0] if above else base + 100000.0)


def _already_hit(rec: H.HullRecord, hood: Neighbourhood | None) -> set[str]:
    """С кем элемент пересекается ДО хода: ход за это не отвечает."""
    if hood is None:
        return set()
    out: set[str] = set()
    lo, hi = rec.bounds()
    for idx in hood.near(lo, hi):
        o = hood.records[idx]
        if o.source_id == rec.source_id:
            continue
        if G.signed_distance(rec.hull, o.hull) < -G.SEP_EPS_MM:
            out.add(o.source_id)
    return out


def _build_move(mover: H.HullRecord, fixed: H.HullRecord,
                hood: Neighbourhood | None, levels, basis: str) -> Move | None:
    best_t: float | None = None
    best_d: tuple[float, float, float] | None = None
    dirs = _directions(mover.hull, fixed.hull)
    for d in dirs:
        t = minimal_exit(mover.hull, fixed.hull, d, ceiling=best_t)
        if t is None:
            continue
        if best_t is None or t < best_t - 1e-9 or (
                abs(t - best_t) <= 1e-9 and (best_d is None or d < best_d)):
            best_t, best_d = t, d
    if best_t is None or best_d is None:
        return None
    vec = tuple(c * best_t for c in best_d)
    moved = G.translate(mover.hull, vec)
    certified = G.signed_distance(moved, fixed.hull) >= -G.SEP_EPS_MM
    blockers: list[str] = []
    hits: list[str] = []
    if not certified:
        blockers.append("uncertified")
    budget = max(BUDGET_FLOOR_MM, BUDGET_FACTOR * _span(mover.hull))
    if best_t > budget:
        blockers.append("exceeds_budget")
    if hood is not None:
        already = _already_hit(mover, hood)
        lo, hi = G.hull_bounds(moved)
        for idx in hood.near(lo, hi):
            other = hood.records[idx]
            if other.source_id in (mover.source_id, fixed.source_id):
                continue
            if other.source_id in already:
                continue
            if G.signed_distance(moved, other.hull) < -G.SEP_EPS_MM:
                hits.append(other.source_id)
                if len(hits) >= 8:
                    break
        if hits:
            blockers.append("hits_third_body")
    band = _level_band(mover, levels)
    if band is not None:
        lo, hi = G.hull_bounds(moved)
        if hi[2] < band[0] - 1.0 or lo[2] > band[1] + 1.0:
            blockers.append("leaves_level_band")
    exact = exit_is_exact(mover.hull, fixed.hull)
    return Move(element_id=mover.source_id, label=mover.label or "",
                category=mover.category,
                minimality=("minimal_over_searched_directions" if exact
                            else "separating_only"),
                directions_searched=len(dirs),
                direction_basis=("axes", "face_normals_mover",
                                 "face_normals_fixed", "certified_translation"),
                direction=tuple(G._norm_zero(c) for c in best_d),
                distance_mm=best_t,
                vector_mm=tuple(G._norm_zero(c) for c in vec),
                certified=certified, legal=not blockers,
                blockers=tuple(blockers), hits=tuple(sorted(hits)),
                rank_basis=basis)


def propose(a: H.HullRecord, b: H.HullRecord, *,
            hood: Neighbourhood | None = None,
            levels: Mapping[str, float] | None = None,
            pair_kind: str = "interference",
            finding_id: str | None = None,
            with_alternative: bool = True) -> Proposal:
    """Предложение по ОДНОЙ паре. Число даётся всегда, когда геометрия его
    даёт; отказ, если он всё же наступил, НАЗВАН."""
    ends = sorted((a, b), key=lambda r: r.source_id)
    fid = finding_id or "%s~%s" % (ends[0].source_id, ends[1].source_id)
    rec = _recommendation(a, b, pair_kind)
    if G.signed_distance(a.hull, b.hull) >= -G.SEP_EPS_MM:
        return Proposal(fid, rec, None, None, "not_overlapping")
    mover, fixed = _order(a, b)
    _, _, basis = mobility_of(mover)
    primary = _build_move(mover, fixed, hood, levels, basis)
    alt = None
    if with_alternative:
        _, _, basis2 = mobility_of(fixed)
        alt = _build_move(fixed, mover, hood, levels, basis2)
    if primary is None and alt is None:
        return Proposal(fid, rec, None, None, "no_certified_direction")
    if primary is None:
        return Proposal(fid, rec, alt, None, None)
    # Незаконный дешёвый ход при законном дорогом: показываем исполнимый
    # первым. Предложение существует ради исполнения, а не ради порядка.
    if not primary.legal and alt is not None and alt.legal:
        return Proposal(fid, rec, alt, primary, None)
    return Proposal(fid, rec, primary, alt, None)


AXIS_NAME = {(1, 0, 0): "по +X", (-1, 0, 0): "по −X", (0, 1, 0): "по +Y",
             (0, -1, 0): "по −Y", (0, 0, 1): "вверх", (0, 0, -1): "вниз"}

_VERB = {"move": "сдвиньте", "review": "чтобы развести, нужно сдвинуть",
         "verify_duplicate": "возможный дубликат; для проверки геометрически развело бы",
         "assembly_relation": "узел; геометрически развело бы"}


def to_russian(p: Proposal) -> str:
    """Строка, которую проектировщик исполняет не переписывая."""
    if p.chosen is None:
        return "%s: хода нет — %s" % (p.finding_id, p.refusal)
    m = p.chosen
    key = tuple(int(round(c)) for c in m.direction)
    where = AXIS_NAME.get(key, "по (%.3f, %.3f, %.3f)" % m.direction)
    head = "%s: %s %s %s %s на %.0f мм" % (
        p.finding_id, _VERB.get(p.recommendation, "сдвиньте"),
        m.label, m.element_id, where, m.distance_mm)
    if m.legal:
        return head + " — ход свободен"
    tail = "; ".join(LEGALITY_BLOCKERS.get(x, x) for x in m.blockers)
    if m.hits:
        tail += " (тела: " + ", ".join(m.hits) + ")"
    return head + " — НО " + tail


def proposals_for(pairs: Iterable[tuple[H.HullRecord, H.HullRecord]], *,
                  hood: Neighbourhood | None = None,
                  levels: Mapping[str, float] | None = None) -> list[Proposal]:
    return [propose(a, b, hood=hood, levels=levels) for a, b in pairs]
