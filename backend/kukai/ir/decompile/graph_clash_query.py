"""КЛЕШ КАК ЗАПРОС С ОБЛАСТЬЮ, а не как слой хранимых рёбер.

Этот модуль НЕ детектор. Он — граница, за которой клеш входит в граф здания, и
устроен он так, чтобы хранить клеш-рёбра было НЕВОЗМОЖНО, а не просто не
принято. Запрет объявлен структурой (`ClashQuery` отдаёт итератор и не
складывает), а не комментарием: комментарий не переживёт того, кто захочет
«просто закэшировать».

═══════════════════════════════════════════════════════════════════════════
ПОЧЕМУ ЗАПРОС, А НЕ СЛОЙ — ПОРОГ НАЗВАН ЗАРАНЕЕ И ЗАМЕРЕН
═══════════════════════════════════════════════════════════════════════════

`демо-v3`, область `all_physical_diagnostic` (замер команды CLASH, 10.08.2026):

| величина | число |
|---|---|
| узлов (оболочек) | 84 120 |
| рёбер-кандидатов широкой фазы | 770 234 |
| рёбер-находок | 769 630 |
| отчёт о них, ОДИН файл JSON | **666 МБ** |
| пиковая RSS процесса | **2.66 ГБ** |
| время узкой фазы | 38.1 с |
| время самой сетки | **0.81 с** |

Отношение рёбер к узлам — **9.15**. Узкая фаза дороже сетки в **47 раз**.
Предел здесь не поиск соседей, а СПИСОК РЁБЕР: удвоение здания (~170 000 узлов)
требует порядка 10 ГБ только на находки. Граф, который попробует держать
клеш-рёбра рядом с узлами, упрётся в ту же стену — но уже на уровне всего
приложения, а не одного модуля.

═══════════════════════════════════════════════════════════════════════════
РЕБРО КЛЕША ТИПИЗИРОВАНО ДВАЖДЫ — И ЭТО ГЛАВНОЕ ИСПРАВЛЕНИЕ
═══════════════════════════════════════════════════════════════════════════

Сегодняшняя «находка» склеивает ТРИ разных отношения:

**(а) КАСАНИЕ** — общая граница, нулевое проникание. Способ, которым здание
СОБРАНО, а не дефект. Замер: `sob62_fas_r23_v19` — 7 804 касания против 19 523
перекрытий; `snowdon_plumb_v5` — 8 559 против 18 030. На треть всех отношений
пары касаются. Касание — ребро СБОРКИ, его место рядом с узлами навсегда, и
показывать его как находку нельзя.

**(б) ПРОНИКАНИЕ ТЕЛ** — пересечение положительного объёма. Физический
конфликт. Сегодня недоказуем почти всегда: `exact` недостижим (65 разборов,
664 870 оболочек, `exact` = 0), поэтому вердикт `confirmed` — мёртвый код, и
это уже записано в схему `clash-report/3`.

**(в) ПЕРЕСЕЧЕНИЕ ОБОЛОЧЕК** — то, что модуль РЕАЛЬНО считает: пересечение двух
КОНСЕРВАТИВНЫХ НАДМНОЖЕСТВ. Это факт о нашем ОПИСАНИИ постройки, не о постройке.

`modality` сегодня размазана по двум модулям и трём полям (`verdict`,
`hull_grade`, `slack`), и ровно на её склейке с `relation` сломались оба
дефекта, чинившиеся 10.08: вакуумный `plate_z_doubling` и ложный
`profile_convexified`.

**ОПРОВЕРЖЕНИЕ — ЭТО РЕБРО, А НЕ ОТСУТСТВИЕ РЕБРА.** Ребро, снятое правилом,
обязано остаться в ответе с ИМЕНЕМ правила; иначе «не нашли» неотличимо от
«не искали», и обе болезни возвращаются. Здесь это условие конструкции:
`ClashRelationEdge` с `REFUTED` без `refuted_by` не строится.

═══════════════════════════════════════════════════════════════════════════
ЧТО ЗАПРОС БЕРЁТ У ГРАФА ВМЕСТО ДОГАДКИ
═══════════════════════════════════════════════════════════════════════════

`resolve.ASSEMBLY_PAIRS` угадывает отношение сборки ПО ПАРЕ ЯРЛЫКОВ
(дверь~стена, импост~панель). Замер: **467 перекрытий из 3 348 (14.0 %)** на
`sob62_r23_v5` отнесены к сборке этой догадкой.

Догадку заменяет ребро `hosted_in`, и данные для него в разборе ЕСТЬ — замер
10.08 по `L0Element.host_id`:

    `sob62_r23_v5`      двери 153/153 (100 %) хозяин `OST_Walls`;
                        окна   31/31  (100 %) хозяин `OST_Walls`
    `sob62_fas_r23_v17` импосты 1 452/1 452 (100 %) хозяин `OST_Walls`;
                        панели    594/1 215 (48.9 %)
    `snowdon_plumb_v5`  двери 143/143, окна 114/114 (100 %)

НО ДОГАДКА ПРОМАХИВАЕТСЯ И В ТУ СТОРОНУ, КОТОРУЮ ЯРЛЫКИ НЕ ОПИСЫВАЮТ, и это
видно только по `host_id`:

* `sob62_fas_r23_v17`: **9 из 14** дверей имеют хозяином `OST_CurtainWallPanels`,
  а не стену;
* `snowdon_plumb_v5`: **89 из 1 425** импостов имеют хозяином панель, а
  **23 из 640** панелей — другую панель;
* `snowdon_plumb_v5`: **21** `OST_GenericModel` и **4** `OST_PlumbingFixtures`
  имеют хозяином `OST_Levels` — ОТМЕТКУ, а не тело. Пары ярлыков такого
  отношения не описывают вовсе, и в графе оно едет отдельным `PLACED_ON_DATUM`.

**И ГЛАВНОЕ ОГРАНИЧЕНИЕ, КОТОРОЕ НЕЛЬЗЯ ЗАМЕСТИ:** `host_id` несёт ответ не
везде. По корпусу висячих ссылок 1 263 из 213 811 (0.59 %), но они СОСРЕДОТОЧЕНЫ:
`snowdon_elec_v1` — **959 из 1 001 (95.8 %)**, четыре снимка Snowdon Plumbing —
**100 %**. Хозяин лежит в СВЯЗАННОМ файле. Поэтому запрос обязан различать
«хозяина нет» и «хозяин вне извлечения», и второй ответ — это ровно тот сигнал,
который делает межраздельную область непустой.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from kukai.ir.decompile.building_graph import (
    BuildingGraph,
    GraphBuildError,
    Modality,
    Relation,
)

__all__ = [
    "ClashQuery",
    "ClashRelation",
    "ClashRelationEdge",
    "ClashScope",
    "ScopeCensus",
    "assembly_relation_of",
]


class ClashRelation(str, Enum):
    """ГЕОМЕТРИЧЕСКОЕ отношение оболочек. Ортогонально `Modality`.

    Три значения вместо одного слова «находка» — см. шапку модуля.
    """

    #: Общая граница, нулевое проникание. Способ сборки, не дефект.
    CONTACT = "contact"
    #: Пересечение положительного объёма (или его консервативной надоценки).
    OVERLAP = "overlap"
    #: Разведены. Ответ, который тоже надо уметь произносить.
    SEPARATED = "separated"


@dataclass(frozen=True, slots=True)
class ClashRelationEdge:
    """Клеш-ребро. Живёт ТОЛЬКО внутри ответа на запрос и никогда не хранится."""

    a: str
    b: str
    relation: ClashRelation
    modality: Modality
    #: Имя ОГРУБЛЕНИЯ либо правила, снявшего ребро. Обязательно при REFUTED.
    refuted_by: str | None = None
    #: Источник оболочки A и B, глубина, нижняя ли это оценка.
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.modality is Modality.REFUTED and not self.refuted_by:
            raise GraphBuildError(
                "клеш-ребро REFUTED без имени огрубления неотличимо от "
                "«не искали» — правило обязано назваться")
        if self.modality is not Modality.REFUTED and self.refuted_by:
            raise GraphBuildError(
                "`refuted_by` при неопровергнутом ребре — ложный след")
        if self.modality is Modality.PROVEN and self.relation is ClashRelation.OVERLAP:
            # Замер: `exact` недостижим (65 разборов, 664 870 оболочек, 0
            # случаев), поэтому доказанное проникание тел сегодня НЕВОЗМОЖНО.
            # Отказ структурный, чтобы `confirmed` не воскрес молча.
            raise GraphBuildError(
                "PROVEN+OVERLAP недостижимо: `exact` = 0 на 664 870 оболочках "
                "65 разборов; доказанное проникание тел сегодня неконструируемо")


@dataclass(frozen=True, slots=True)
class ScopeCensus:
    """ЗНАМЕНАТЕЛЬ запроса. Без него ответ «клешей нет» не значит ничего.

    Закон переписи CLASH (`eligible = hulled + unsupported + missing_geometry`)
    сходится сегодня по каждой категории каждого из 65 разборов — 0 молчаливых
    выпадений на ~1.03 млн элементов. Здесь тот же закон на узлах ГРАФА.
    """

    nodes_in_scope: int
    nodes_with_hull: int
    refusals: Mapping[str, int]

    @property
    def refused(self) -> int:
        return sum(self.refusals.values())

    def assert_balanced(self) -> None:
        if self.nodes_with_hull + self.refused != self.nodes_in_scope:
            raise GraphBuildError(
                f"перепись области не сходится: узлов {self.nodes_in_scope}, "
                f"с оболочкой {self.nodes_with_hull}, названных отказов "
                f"{self.refused}")


@dataclass(frozen=True, slots=True)
class ClashScope:
    """ОБЛАСТЬ запроса. Клеш без области — это 770 234 ребра и 666 МБ.

    `scope_id` уже существует в модуле клешей; здесь он ОБЯЗАТЕЛЕН, потому что
    именно он отделяет запрос от слоя.
    """

    scope_id: str
    node_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not self.scope_id:
            raise GraphBuildError(
                "запрос без `scope_id` есть слой рёбер под другим именем")


#: Отношения графа, при которых пересечение оболочек есть СБОРКА, а не конфликт.
#: Это СВИДЕТЕЛЬСТВО (прочитанное `host_id`), а не догадка по паре ярлыков.
_ASSEMBLY_RELATIONS: frozenset[Relation] = frozenset({
    Relation.HOSTED_IN,
    Relation.PLACED_ON_DATUM,
})


def assembly_relation_of(graph: BuildingGraph, a: str, b: str) -> str | None:
    """Объявлено ли между парой отношение СБОРКИ — по графу, а не по ярлыкам.

    Возвращает имя отношения, либо `"host_outside_extraction"`, если одна
    сторона объявила хозяина, которого в извлечении нет (это НЕ «нет
    отношения»), либо None.

    Заменяет `resolve.ASSEMBLY_PAIRS`: 467 из 3 348 перекрытий (14.0 %) на
    `sob62_r23_v5` классифицировались догадкой по паре меток.
    """
    for src, dst in ((a, b), (b, a)):
        for edge in graph.out_edges(src):
            if edge.relation not in _ASSEMBLY_RELATIONS:
                continue
            if edge.dst == dst and edge.modality is Modality.PROVEN:
                return edge.relation.value
    # Одна сторона объявила хозяина ВНЕ извлечения — ответить «нет отношения»
    # значило бы выдать нашу слепоту за факт о здании.
    for src in (a, b):
        for edge in graph.out_edges(src):
            if (edge.relation is Relation.HOSTED_IN
                    and edge.modality is Modality.UNRESOLVED_TARGET):
                return "host_outside_extraction"
    return None


class ClashQuery:
    """Клеш как ЗАПРОС. Отдаёт итератор и НИЧЕГО не накапливает.

    Отсутствие метода, возвращающего список, — не забывчивость: это и есть
    запрет. Замер называет цену списка заранее (770 234 ребра, 666 МБ, 2.66 ГБ
    RSS на `демо-v3`), поэтому список не предлагается вовсе.
    """

    __slots__ = ("graph", "scope", "_pairs", "_classify", "census")

    def __init__(
        self,
        graph: BuildingGraph,
        scope: ClashScope,
        *,
        candidate_pairs: Callable[[], Iterable[tuple[str, str]]],
        classify: Callable[[str, str], ClashRelationEdge | None],
        census: ScopeCensus,
    ) -> None:
        unknown = scope.node_ids - set(graph.nodes)
        if unknown:
            raise GraphBuildError(
                f"область называет {len(unknown)} узлов, которых в графе нет; "
                f"первый — {sorted(unknown)[0]!r}")
        self.graph = graph
        self.scope = scope
        self._pairs = candidate_pairs
        self._classify = classify
        self.census = census
        census.assert_balanced()

    def __iter__(self) -> Iterator[ClashRelationEdge]:
        """Единственный способ получить клеш-рёбра — пройти по ним ОДИН раз."""
        for a, b in self._pairs():
            if a not in self.scope.node_ids or b not in self.scope.node_ids:
                continue
            assembly = assembly_relation_of(self.graph, a, b)
            edge = self._classify(a, b)
            if edge is None:
                continue
            if assembly is not None and edge.modality is not Modality.REFUTED:
                # Отношение сборки СНИМАЕТ находку — и ребро ОСТАЁТСЯ, с
                # именем правила. `resolve` здесь угадывал по ярлыкам.
                edge = ClashRelationEdge(
                    a=edge.a, b=edge.b, relation=edge.relation,
                    modality=Modality.REFUTED,
                    refuted_by=f"assembly_relation:{assembly}",
                    evidence={**dict(edge.evidence),
                              "assembly_from": "building_graph",
                              "was_modality": edge.modality.value})
            yield edge

    def tally(self) -> Mapping[str, int]:
        """Свод по одному проходу. Рёбра не сохраняются — только счётчики."""
        from collections import Counter
        counter: Counter[str] = Counter()
        for edge in self:
            counter[f"{edge.relation.value}/{edge.modality.value}"] += 1
            if edge.refuted_by:
                counter[f"refuted_by:{edge.refuted_by}"] += 1
        return dict(counter)
