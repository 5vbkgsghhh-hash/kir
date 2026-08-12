"""Закрытая таблица «категория → пригодность → источник оболочки → грейд».

Закон переписи §18 здесь буквальный: КАЖДЫЙ элемент модели обязан выйти из этой
таблицы ровно с одним исходом — оболочка либо названная причина её отсутствия.
Молча выпасть не может ни один класс: неизвестная категория попадает в
`unsupported` с причиной `kind_outside_table`, а не исчезает.

Почему таблица закрытая, а не «если получилось». Детектор, который построил
оболочки для половины здания и нашёл ноль клешей, неотличим от детектора,
который искал честно. Единственная защита — счётчики, сходящиеся к переписи:
`eligible = hulled + unsupported + missing_geometry`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from kukai.clash import decompose as D
from kukai.clash import geom as G

#: Грейд оболочки — насколько она обжимает элемент.
#:
#: `exact`        — оболочка совпадает с телом (прямая труба круглого сечения);
#: `conservative` — содержит тело и огрубляет НАЗВАННЫМ образом (после волны
#:                  DECOMPOSE подошва контура точна, но Z по-прежнему берётся
#:                  из объявленной отметки, а дуга раздута наружу на стрелку);
#: `coarse`       — только габаритный бокс: содержит тело и больше ничего про
#:                  него не утверждает.
GRADES = ("exact", "conservative", "coarse")

#: Допуск на грейд: насколько глубоко пара должна войти друг в друга, чтобы
#: назвать это клешем. У точной оболочки допуска нет. У грубой доказать
#: проникание вообще нельзя (ревью №14), поэтому её вердикт максимум
#: `possible` — а допуск удерживает от объявления клешем касания габаритов.
TOL_GRADE_MM = {"exact": 0.0, "conservative": 1.0, "coarse": 25.0}


#: Источники оболочки, разрешённые категории. Ревью №12: строка, заявляющая
#: ВСЕ три источника для каждой пригодной категории, самосогласована и пуста —
#: у мебели нет контура подошвы, у стены сегодня нет сечения. Список источников
#: обязан быть свойством КАТЕГОРИИ, иначе матрица покрытия ничего не обещает.
SOURCES_SKETCH = ("profile", "bbox")
SOURCES_AXIS = ("axis_section", "bbox")
SOURCES_BBOX = ("bbox",)
#: Полоса вокруг оси × [z0, z1]. Вход — `el["prism"]`, собранный только из
#: доказанных чисел ТИПА.
#:
#: НИ ОДНА КАТЕГОРИЯ СЕГОДНЯ ЭТОГО ИСТОЧНИКА НЕ ИМЕЕТ, И ЭТО ЗАМЕР, А НЕ
#: ЗАБЫВЧИВОСТЬ. Волна sections (09.08.2026) снабдила снапшот толщиной стены
#: (`WallType.Width`) и проверила закон консервативности внешним свидетелем —
#: настоящими габаритами Revit 800 стен здания Snowdon:
#:
#:   выход тела ВДОЛЬ оси    409 стен из 800, медиана 6.3, p99 757, max 1362 мм
#:   выход тела ПОПЕРЁК оси   93 стены из 800,                      max 2854 мм
#:
#: Продольный выход объясняется примыканиями и почти весь (703 из 707)
#: покрывается ТОЧНЫМ расчётом стыка по самой пачке. Поперечный — не
#: объясняется ничем, что программа выражает: 93 стены шире собственной
#: `WallType.Width` вплоть до 2854 мм (пакетные сборки, отредактированный
#: профиль, свесы). Итог с точным стыком — 97 нарушений из 800, то есть
#: замок `clash.tools.wall_prism_gate` («ноль нарушений на всей выборке»)
#: НЕ ОТКРЫТ, и стена остаётся на габарите.
#:
#: Билдер, вход и эта строка живут здесь затем, чтобы день, когда замок
#: откроется, стоил одну правку в таблице, а не проектирования заново.
SOURCES_PRISM = ("prism", "bbox")


#: ПОЧЕМУ СТЕНЕ НЕ ДАЮТ ПОЛОСУ — ЗАМЕР 11.08.2026 ПО ВСЕМУ КОРПУСУ.
#:
#: Прежняя запись (выше) верна и НЕИСПОЛЬЗУЕМА: «полоса провалилась на 2854 мм
#: у 97 стен из 800» говорит, что попытка была неудачной, но не говорит, ЧТО
#: именно откроет ворота. По ней следующая сессия предложит полосу заново —
#: «стена ведь имеет толщину» звучит очевидно. Здесь та же дверь заперта
#: разложением по классам, из которого видно и почему она заперта, и чем её
#: отпирают.
#:
#: ЗНАМЕНАТЕЛЬ: 220 871 стена, все читаемые разборы корпуса
#: (`/tmp/clashwork/w2_wall_width.py`, `w2_prize.py`).
#:
#: (1) ТОЛЩИНЫ В ДАННЫХ НЕТ ВООБЩЕ. Ни одна стена корпуса не несёт ключа
#:     `prism`; весь `params` стены — WALL_BASE_OFFSET, WALL_HEIGHT_TYPE,
#:     WALL_KEY_REF_PARAM, WALL_TOP_OFFSET, WALL_USER_HEIGHT_PARAM. Записи
#:     типа в `L0.jsonl` нет (виды записей: header, link, element,
#:     category_status, footer). То есть `_prism_record` сегодня даже не
#:     доходит до проверки — он выходит на первой строке.
#:
#: (2) 55.9 % СТЕН ПОЛОСА НЕ УТОЧНЯЕТ ПО ПОСТРОЕНИЮ. 123 418 стен осевыровнены,
#:     и у них прямоугольник вокруг оси СОВПАДАЕТ с габаритным боксом. Половина
#:     аргумента снимается до всякого спора о содержании: обжимать нечего.
#:
#: (3) 39.3 % ДИАГОНАЛЬНЫХ СТЕН ПРОТИВОРЕЧАТ САМИ СЕБЕ. Габарит прямой стены
#:     ПЕРЕОПРЕДЕЛЯЕТ её ширину: dx = L·|ux| + w·|uy| и dy = L·|uy| + w·|ux| —
#:     два уравнения на одно неизвестное, поэтому w считается дважды и
#:     независимо. Из 31 915 диагональных стен согласны 19 368, а у 12 547
#:     (39.3 %) две оценки расходятся более чем на 1 мм, вплоть до 587.6 мм.
#:     Это не «данные неточны» — это данные, НЕСОВМЕСТИМЫЕ с моделью
#:     прямоугольной стены. Подгонять w под одну из двух оценок значит выбирать,
#:     какое из двух измерений объявить ложным.
#:
#: (4) 17.5 % ОСЕВЫРОВНЕННЫХ ИМЕЮТ ОСЕВОЙ ВЫНОС. У 21 556 стен габарит длиннее
#:     оси более чем на 1 мм, до 250 мм: стыки выталкивают материал ЗА линию
#:     расположения. Ось не есть тело даже по длине, не только по ширине.
#:
#: (5) ПРОВЕРИТЬ НЕЧЕМ, И ЭТО НЕ ВРЕМЕННО. Треугольников стен в корпусе нет:
#:     единственный разбор с `geometry.bundle.json` (`snowdon_plumb_v4`) несёт
#:     пять стен, и НИ ОДНОЙ из них нет в индексе геометрии. Но важнее другое, и
#:     оно переживёт появление корпуса: ГАБАРИТНЫЕ ВОРОТА НЕ МОГУТ ПРОВЕРИТЬ
#:     ПОЛОСУ В ПРИНЦИПЕ. Полоса лежит СТРОГО ВНУТРИ габарита, поэтому условие
#:     «полоса ⊇ габарит» проваливается всегда и ничего не диагностирует, а
#:     «полоса ⊆ габарит» выполняется всегда и ничего не обещает про ТЕЛО. Это
#:     довод формы, а не нехватки данных, — тот же, по которому габаритные
#:     ворота не умеют проверить капсулу (см. `tools/mesh_gate`).
#:
#: (6) ПРИЗ, РАДИ ПОЛНОТЫ КАРТИНЫ. У 19 368 согласованных диагональных стен
#:     (8.8 % корпуса) площадь полосы — медиана 50.1 % габаритной, p10 35.1 %,
#:     минимум 3.6 %. Половина следа у одной стены из одиннадцати, и только
#:     если содержание ДОКАЗАНО. Отгрузить эти 8.8 % на недоказанном допущении
#:     нельзя: тело меньше настоящего прячет клеш молча, а это единственный
#:     отказ, который доезжает до стройки.
#:
#: ЧТО ОТКРОЕТ ВОРОТА, в порядке полезности:
#:
#:   1. ТРЕУГОЛЬНИКИ СТЕН в связке геометрии для АРХИТЕКТУРНОЙ модели.
#:      Инструмент уже написан: `clash/tools/mesh_gate` сверяет каждую вершину
#:      настоящего тела с оболочкой независимым кодом и решает вопрос за один
#:      прогон. Это снимает пункт (5) целиком — и только это его снимает.
#:   2. ШИРИНА ТИПА (`WallType.Width` либо запись типа в L0). Без пункта 1 она
#:      недостаточна: она закрывает пункт (1), но не (3) и не (4), потому что
#:      расхождение оценок и осевой вынос — свойства ТЕЛА, а не номинала.
#:
#: Оба входа лежат вне этого модуля (`kukai/ir/**`), поэтому запись здесь —
#: не задача, а условие приёмки: день, когда данные придут, обязан стоить одну
#: правку в `KIND_TABLE` и один прогон ворот, а не проектирование заново.
WALL_BAND_REFUSAL: dict[str, object] = {
    "measured_on": "2026-08-11",
    "walls_total": 220871,
    "axis_aligned_no_gain": 123418,
    "axis_aligned_axial_overhang_gt1mm": 21556,
    "axis_overhang_max_mm": 250.0,
    "diagonal": 31915,
    "diagonal_consistent": 19368,
    "diagonal_self_contradictory": 12547,
    "width_disagreement_max_mm": 587.6,
    "non_line_axis_or_no_location_curve": 63231,
    "wall_meshes_in_corpus": 0,
    "band_area_over_bbox_area_p50": 0.501,
    "opens_with": ("wall_triangles_in_geometry_bundle", "wall_type_width"),
    "why_bbox_gate_cannot_decide": (
        "полоса лежит строго внутри габарита: «полоса ⊇ габарит» ложно всегда, "
        "«полоса ⊆ габарит» истинно всегда и про тело не говорит ничего"),
}


#: Откуда берётся сечение — из `params` строки L0 (эмиссия d154196e). Ключ
#: `params` РАВЕН имени BuiltInParameter, поэтому здесь нет ни одного
#: «похожего» имени: `WALL_ATTR_WIDTH` в перечислении Revit отсутствует вовсе.
#:
#: Правило — свойство КАТЕГОРИИ, ровно как `sources` (ревью №12). Труба обязана
#: читать диаметр трубы, лоток — габарит лотка; «любое число, похожее на
#: сечение» было бы тем же самосогласованным и пустым списком источников.
#:
#: `round` — параметры, дающие диаметр (радиус = d/2). `rect` — пары
#: (ширина, высота), дающие ПОЛУДИАГОНАЛЬ hypot(w,h)/2: поворот прямоугольного
#: сечения вокруг оси в L0 не снят, поэтому оболочка обязана содержать коробку
#: при ЛЮБОМ угле крена, а это ровно цилиндр полудиагонального радиуса.
SECTION_RULES: dict[str, dict[str, tuple]] = {
    "OST_PipeCurves": {
        "round": ("RBS_PIPE_OUTER_DIAMETER", "RBS_PIPE_DIAMETER_PARAM"),
        "rect": ()},
    "OST_DuctCurves": {
        "round": ("RBS_CURVE_DIAMETER_PARAM",),
        "rect": (("RBS_CURVE_WIDTH_PARAM", "RBS_CURVE_HEIGHT_PARAM"),)},
    "OST_CableTray": {
        "round": (),
        "rect": (("RBS_CABLETRAY_WIDTH_PARAM", "RBS_CABLETRAY_HEIGHT_PARAM"),)},
    "OST_Conduit": {
        "round": ("RBS_CONDUIT_OUTER_DIAM_PARAM", "RBS_CONDUIT_DIAMETER_PARAM"),
        "rect": ()},
}

#: ЧТО ИМЕННО описывает круглый параметр — и, следовательно, содержит ли
#: капсула этого радиуса тело. Красная команда, находка R3: номинал НЕ
#: содержит. У ДУ100 `RBS_PIPE_DIAMETER_PARAM` = 100, а наружный — 114.3;
#: капсула радиуса 50 не содержит тела радиуса 57.15, и это в паре MVP.
#:
#: Классификация взята из СТРОКИ `<summary>` перечисления в `RevitAPI.xml`
#: (сверено во всех шести версиях; существование каждого имени доказано
#: компиляцией 6/6), а не из привычки:
#:
#:   RBS_PIPE_DIAMETER_PARAM      "Diameter"              -> номинал
#:   RBS_PIPE_OUTER_DIAMETER      "Outside Diameter"      -> наружный
#:   RBS_CONDUIT_DIAMETER_PARAM   "Diameter(Trade Size)"  -> номинал прямым текстом
#:   RBS_CONDUIT_OUTER_DIAM_PARAM "Outside Diameter"      -> наружный
#:   RBS_CURVE_DIAMETER_PARAM     "Diameter"              -> см. ниже
#:
#: У ВОЗДУХОВОДА наружного параметра в API НЕТ ни в одной из шести версий
#: (сверено). Значит `RBS_CURVE_DIAMETER_PARAM` — единственное описание его
#: сечения, и назвать его номиналом не с чем сравнивать: `modelled`. Это
#: ДОПУЩЕНИЕ, и оно названо здесь, а не спрятано в умолчание.
DIAMETER_KIND: dict[str, str] = {
    "RBS_PIPE_OUTER_DIAMETER": "outer",
    "RBS_PIPE_DIAMETER_PARAM": "nominal",
    "RBS_CONDUIT_OUTER_DIAM_PARAM": "outer",
    "RBS_CONDUIT_DIAMETER_PARAM": "nominal",
    "RBS_CURVE_DIAMETER_PARAM": "modelled",
}

#: Чтения, которыми РАЗРЕШЕНО обосновывать капсулу. Номинал сюда не входит:
#: закон консервативности не знает исключений, а «почти содержит» — не
#: содержит. Ровно то же решение, что у дуги в `profile_refusal`: нет
#: доказательства — откат в габаритный бокс, который приходит из НАСТОЯЩЕЙ
#: геометрии Revit и тело содержит.
DIAMETER_KIND_ALLOWED = ("outer", "modelled")

#: ВСЕ параметры сечения, которые L0 умеет снимать, — закрытый список,
#: обязанный совпадать с `extract.SECTION_PARAM_NAMES` (равенство держит тест
#: `test_the_closed_section_list_matches_the_emission`). Он шире `SECTION_RULES`
#: ровно на те четыре имени, которыми таблице пользоваться ЗАПРЕЩЕНО: толщина
#: стены и структурный профиль сняты, но оболочку не обосновывают (ревью №2,
#: №3, №10). Именно эта разница и позволяет отчёту сказать «число есть, подъём
#: запрещён» вместо молчаливого нуля.
ALL_SECTION_PARAM_NAMES: tuple[str, ...] = (
    "RBS_CABLETRAY_HEIGHT_PARAM",
    "RBS_CABLETRAY_WIDTH_PARAM",
    "RBS_CONDUIT_DIAMETER_PARAM",
    "RBS_CONDUIT_OUTER_DIAM_PARAM",
    "RBS_CURVE_DIAMETER_PARAM",
    "RBS_CURVE_HEIGHT_PARAM",
    "RBS_CURVE_WIDTH_PARAM",
    "RBS_PIPE_DIAMETER_PARAM",
    "RBS_PIPE_OUTER_DIAMETER",
    "STRUCTURAL_SECTION_COMMON_DIAMETER",
    "STRUCTURAL_SECTION_COMMON_HEIGHT",
    "STRUCTURAL_SECTION_COMMON_WIDTH",
    "WALL_ATTR_WIDTH_PARAM",
)

#: Параметры сечения, которые НЕ являются длиной. `WALL_CROSS_SECTION` —
#: перечисление («Cross-Section»), отличающее vertical от slanted/tapered.
#: Оболочку по нему не строят: он решает, ПОЗВОЛЕНО ли строить призму вообще.
#: Держится отдельно от `ALL_SECTION_PARAM_NAMES`, потому что `> 0` для
#: перечисления бессмысленно: 0 — законное значение, а не отсутствие.
SECTION_ENUM_PARAM_NAMES: tuple[str, ...] = (
    "WALL_BOTTOM_IS_ATTACHED",
    "WALL_CROSS_SECTION",
    "WALL_TOP_IS_ATTACHED",
)

#: Что обязано быть ДОКАЗАНО, прежде чем стене разрешат призму по одной
#: толщине (ревью кодекса №10). Ни одного из трёх L0 сегодня не снимает:
#: `WALL_CROSS_SECTION` отличает vertical от slanted/tapered, состав
#: `CompoundStructure` по высоте — stacked и vertically compound, список
#: sweeps — выступы за номинальные width/2. Без них призма по width
#: НЕКОНСЕРВАТИВНА для части стен, то есть допускает пропуск клеша.
WALL_PRISM_EVIDENCE = ("WALL_CROSS_SECTION",
                       "wall_compound_layers_by_height",
                       "wall_sweeps")


@dataclass(frozen=True)
class KindRule:
    """Строка закрытой таблицы."""
    #: Физический элемент модели, у которого обязана быть оболочка. False —
    #: датум/аннотация: оси, уровни, зоны, растры. Они не участвуют ни в
    #: переписи пригодных, ни в поиске.
    eligible: bool
    #: Класс для пар MVP: "mep" (труба/воздуховод/лоток) или "struct"
    #: (стена/пол/колонна). None — вне пар MVP, оболочка строится, но пара с
    #: ней в узкую фазу не идёт.
    mvp_side: str | None = None
    #: Короткое имя класса для `pair_class` в находке.
    label: str = ""
    note: str = ""
    #: Чем этой категории РАЗРЕШЕНО обосновывать оболочку, от точного к грубому.
    sources: tuple[str, ...] = SOURCES_BBOX


#: Категории Revit -> правило. Список закрыт: всё, чего здесь нет, — явный
#: `kind_outside_table`, а не тихий пропуск.
KIND_TABLE: dict[str, KindRule] = {
    # ── несущее и ограждающее (сторона struct пар MVP)
    # Стена — только габарит, и это ЗАМЕРЕННЫЙ отказ, а не недоделка.
    # Разложение по классам, знаменатель 220 871 стена и список того, что
    # ворота откроет, — в `WALL_BAND_REFUSAL` и в записи над ним. Коротко:
    # 55.9 % стен полоса не уточняет по построению, 39.3 % диагональных
    # противоречат сами себе до 587.6 мм, 17.5 % осевыровненных выносят тело
    # за ось до 250 мм, а габаритные ворота не способны проверить полосу В
    # ПРИНЦИПЕ. Стена при этом НЕ выпадает из поиска: она в нём коробкой
    # (замер: 691 оболочка из 695 на `sob62_r23_v5`, вырожденных ноль).
    "OST_Walls": KindRule(True, "struct", "wall", sources=SOURCES_BBOX),
    "OST_Floors": KindRule(True, "struct", "floor", sources=SOURCES_SKETCH),
    "OST_StructuralColumns": KindRule(True, "struct", "column", sources=SOURCES_BBOX),
    "OST_Columns": KindRule(True, "struct", "column", sources=SOURCES_BBOX),
    # Балка эксцентрична относительно оси (justification) — ревью №3; до
    # category-specific билдера только габарит.
    "OST_StructuralFraming": KindRule(True, "struct", "beam", sources=SOURCES_BBOX),
    "OST_StructuralFoundation": KindRule(True, "struct", "foundation",
                                         sources=SOURCES_BBOX),
    "OST_Roofs": KindRule(True, "struct", "roof", sources=SOURCES_SKETCH),
    # ── инженерия (сторона mep пар MVP)
    "OST_PipeCurves": KindRule(True, "mep", "pipe", sources=SOURCES_AXIS),
    "OST_DuctCurves": KindRule(True, "mep", "duct", sources=SOURCES_AXIS),
    # Гибкие трассы: ось между концами НЕ описывает прогиб (ревью №3) — только
    # габарит, пока нет захвата настоящей кривой.
    "OST_FlexPipeCurves": KindRule(True, "mep", "pipe", sources=SOURCES_BBOX),
    "OST_FlexDuctCurves": KindRule(True, "mep", "duct", sources=SOURCES_BBOX),
    "OST_CableTray": KindRule(True, "mep", "tray", sources=SOURCES_AXIS),
    "OST_Conduit": KindRule(True, "mep", "conduit", sources=SOURCES_AXIS),
    # ── R2 красных: ФИТИНГИ И АРМАТУРА ТРАСС. На `sklnk_eom_r26_v8` лотков 75,
    #    фитингов лотка 64 — 46.0 % трассы по числу элементов не имело оболочки
    #    ВООБЩЕ и уходило в `kind_outside_table`. И это ровно углы, тройники и
    #    переходы, то есть места, где трасса ШИРЕ прямого участка. Оси у них
    #    нет (фитинг — не отрезок), поэтому только габарит; но габарит есть, и
    #    он тело содержит.
    "OST_PipeFitting": KindRule(True, "mep", "pipe_fitting", sources=SOURCES_BBOX),
    "OST_DuctFitting": KindRule(True, "mep", "duct_fitting", sources=SOURCES_BBOX),
    "OST_CableTrayFitting": KindRule(True, "mep", "tray_fitting",
                                     sources=SOURCES_BBOX),
    "OST_ConduitFitting": KindRule(True, "mep", "conduit_fitting",
                                   sources=SOURCES_BBOX),
    "OST_PipeAccessory": KindRule(True, "mep", "pipe_accessory",
                                  sources=SOURCES_BBOX),
    "OST_DuctAccessory": KindRule(True, "mep", "duct_accessory",
                                  sources=SOURCES_BBOX),
    "OST_DuctTerminal": KindRule(True, "mep", "duct_terminal",
                                 sources=SOURCES_BBOX),
    "OST_Sprinklers": KindRule(True, "mep", "sprinkler", sources=SOURCES_BBOX),
    # ── R4 красных: ИЗОЛЯЦИЯ И ФУТЕРОВКА. Тело есть в модели ОТДЕЛЬНЫМ
    #    элементом со своим габаритом, и мы его не спрашивали. ДУ20 (наружный
    #    26.9) + 50 мм изоляции: оболочка трубы покрывала 4.5 % площади
    #    сечения препятствия. Берём тело изоляции, а не раздуваем радиус на
    #    её толщину: первое не требует верить в число.
    "OST_PipeInsulations": KindRule(True, "mep", "pipe_insulation",
                                    sources=SOURCES_BBOX),
    "OST_DuctInsulations": KindRule(True, "mep", "duct_insulation",
                                    sources=SOURCES_BBOX),
    "OST_DuctCurvesInsulation": KindRule(True, "mep", "duct_insulation",
                                         sources=SOURCES_BBOX),
    "OST_DuctLinings": KindRule(True, "mep", "duct_lining", sources=SOURCES_BBOX),
    "OST_FabricationPipeworkInsulation": KindRule(
        True, "mep", "pipe_insulation", sources=SOURCES_BBOX),
    # ── физические, но вне пар MVP: оболочка строится, перепись сходится,
    #    в узкую фазу не идут (много легальных примыканий — вторая очередь)
    "OST_Doors": KindRule(True, None, "door"),
    "OST_Windows": KindRule(True, None, "window"),
    "OST_CurtainWallPanels": KindRule(True, None, "curtain_panel"),
    "OST_CurtainWallMullions": KindRule(True, None, "mullion"),
    "OST_GenericModel": KindRule(True, None, "generic"),
    "OST_SpecialityEquipment": KindRule(True, None, "equipment"),
    "OST_StairsRailing": KindRule(True, None, "railing"),
    "OST_Stairs": KindRule(True, None, "stairs"),
    "OST_Furniture": KindRule(True, None, "furniture"),
    "OST_Casework": KindRule(True, None, "casework"),
    "OST_PlumbingFixtures": KindRule(True, None, "fixture"),
    "OST_MechanicalEquipment": KindRule(True, None, "equipment"),
    "OST_Ceilings": KindRule(True, None, "ceiling"),
    "OST_Ramps": KindRule(True, None, "ramp"),
    "OST_CurtaSystem": KindRule(True, None, "curtain_system"),
    # ── R2 красных, вторая половина: физические тела, до сих пор уходившие в
    #    `kind_outside_table` (по корпусу 991 элемент: электрооборудование 516,
    #    фитинги лотка 384, DirectShape 91). Оболочка им строится, в пары MVP
    #    они не идут — оборудование против стены это отдельный разговор.
    "OST_ElectricalEquipment": KindRule(True, None, "electrical_equipment"),
    "OST_ElectricalFixtures": KindRule(True, None, "electrical_fixture"),
    "OST_LightingDevices": KindRule(True, None, "lighting_device"),
    "OST_LightingFixtures": KindRule(True, None, "lighting_fixture"),
    # Импорт целого раздела (DWG/IFC) давал НОЛЬ оболочек — то есть был
    # невидим для поиска целиком.
    "DirectShape": KindRule(True, None, "direct_shape"),
    "ImportInstance": KindRule(True, None, "import_instance"),
    # Ферма — КОНТЕЙНЕР: её тела суть её элементы (OST_StructuralFraming),
    # которые уже в таблице. Оболочка строится ради переписи, в пары MVP не
    # идёт, иначе один и тот же металл считался бы дважды.
    "OST_StructuralTruss": KindRule(True, None, "truss",
                                    "контейнер: тела — его элементы"),
    # Линии витражной сетки — ДАТУМ (раскладка), а не тело.
    "OST_CurtainGridsWall": KindRule(False, None, "curtain_grid", "датум"),
    "OST_CurtainGridsRoof": KindRule(False, None, "curtain_grid", "датум"),
    "OST_CurtainGridsCurtaSystem": KindRule(False, None, "curtain_grid", "датум"),
    # Пространства ОВ — объём, а не тело (как помещения).
    "OST_MEPSpaces": KindRule(False, None, "mep_space", "пространство, не тело"),
    # ── датумы и аннотации: физического тела нет, оболочки не бывает
    "OST_Grids": KindRule(False, None, "grid", "датум"),
    "OST_Levels": KindRule(False, None, "level", "датум"),
    "OST_Areas": KindRule(False, None, "area", "аннотация"),
    "OST_RasterImages": KindRule(False, None, "raster", "аннотация"),
    "OST_Rooms": KindRule(False, None, "room", "пространство, не тело"),
    "OST_CLines": KindRule(False, None, "refplane", "датум"),
    "OST_Dimensions": KindRule(False, None, "dimension", "аннотация"),
    "OST_Lines": KindRule(False, None, "line", "аннотация"),
    "OST_SketchLines": KindRule(False, None, "sketch", "аннотация"),
}

#: Пары классов MVP: межраздельные клеши, самые дорогие на стройке.
MVP_PAIR = ("mep", "struct")



#: Вырожденность оболочки: тело нулевого объёма. Не ошибка чтения — так
#: пришёл габарит из Revit; но оболочка нулевого объёма НЕ МОЖЕТ доказать
#: клеш, а её пары ничего не значат, и до волны 10.08.2026 их никто не считал.
#:
#: Замер 10.08.2026 по всему складу (65 читаемых разборов, 664 870 оболочек с
#: габаритом): вырождены 64 357, то есть 9.7 %.
#:
#:   OST_GenericModel        35 225   (плоские 32 306, точки 2 919)
#:   OST_Furniture           14 088
#:   OST_PlumbingFixtures     8 591
#:   OST_StructuralFraming    6 408   ← сторона `struct` пар MVP
#:   OST_SpecialityEquipment     45
#:   OST_Walls                    6
#:
#: ЧЕСТНО О ТОМ, ЧТО ЭТО ЗНАЧИТ. Ни у одной из них в данных НЕТ независимого
#: свидетеля протяжённости: ни оси, ни сечения, ни высоты, ни контура —
#: проверено тем же замером (`no_independent_witness` = 67 108 из 67 108).
#: Значит закон содержания здесь НЕ НАРУШЕН и НЕ ПОДТВЕРЖДЁН: сказать, что
#: тело шире своего габарита, нечем. Отсюда и форма отчёта — счётчик, а не
#: отказ: число публикуется, вывод не делается.
DEGENERACIES = ("ok", "aabb_point", "aabb_line", "aabb_plane",
                "prism_zero_area", "prism_zero_height", "prism_degenerate_footprint",
                "capsule_zero_radius")


def hull_degeneracy(hull: "G.Hull") -> str:
    """Имя вырожденности оболочки. `ok` — тело ненулевого объёма.

    У объединения вырожденность — свойство ВСЕГО тела, а не куска: заметание
    законно выпускает отрезки-ячейки на защемлениях области, и объявлять из-за
    одной такой ячейки нулевым весь пол значило бы читать перепись наоборот.
    """
    if isinstance(hull, G.Capsule):
        return "capsule_zero_radius" if hull.radius <= 0.0 else "ok"
    if isinstance(hull, G.PrismSet):
        if not hull.pieces:
            return "prism_degenerate_footprint"
        if hull.z1 - hull.z0 <= 0.0:
            return "prism_zero_height"
        total = 0.0
        for fp in hull.pieces:
            n = len(fp)
            if n < 3:
                continue
            total += abs(sum(fp[i][0] * fp[(i + 1) % n][1]
                             - fp[(i + 1) % n][0] * fp[i][1] for i in range(n)))
        return "prism_zero_area" if total <= 0.0 else "ok"
    if isinstance(hull, G.Prism):
        fp = hull.footprint
        if len(fp) < 3:
            return "prism_degenerate_footprint"
        n = len(fp)
        area2 = sum(fp[i][0] * fp[(i + 1) % n][1] - fp[(i + 1) % n][0] * fp[i][1]
                    for i in range(n))
        if abs(area2) <= 0.0:
            return "prism_zero_area"
        return "prism_zero_height" if hull.z1 - hull.z0 <= 0.0 else "ok"
    lo, hi = hull.bounds()
    zero = sum(1 for k in range(3) if hi[k] - lo[k] <= 0.0)
    return {0: "ok", 1: "aabb_plane", 2: "aabb_line", 3: "aabb_point"}[zero]

@dataclass
class HullRecord:
    """Одна запись снапшота: оболочка и всё, чем она обоснована."""
    source_id: str
    category: str
    label: str
    mvp_side: str | None
    hull: G.Hull
    grade: str
    hull_source: str          # profile | axis_section | bbox
    level_id: str | None = None
    type_name: str | None = None
    #: Сечение, которым обоснована оболочка (волна D2-A). `None` — сечения у
    #: элемента нет ИЛИ его категории источник `axis_section` не разрешён;
    #: различает эти два случая перепись снапшота, а не это поле.
    section_radius_mm: float | None = None
    section_round: bool | None = None
    #: Имя параметра(ов) L0, из которого число взято. Отчёт без него не может
    #: сказать, ЧЕМ обоснована оболочка, — а «conservative» без обоснования
    #: ничем не лучше «coarse».
    section_source: str | None = None
    extra: dict = field(default_factory=dict)

    def bounds(self):
        return self.hull.bounds()


@dataclass
class Refusal:
    source_id: str
    category: str
    bucket: str               # unsupported | missing_geometry | not_eligible
    reason: str


def _pt3(v: Any) -> G.Pt3 | None:
    if isinstance(v, (list, tuple)) and len(v) >= 3 and all(G._finite(x) for x in v[:3]):
        return (float(v[0]), float(v[1]), float(v[2]))
    return None


def _valid_box(lo: Any, hi: Any) -> tuple[G.Pt3, G.Pt3] | None:
    a, b = _pt3(lo), _pt3(hi)
    if a is None or b is None:
        return None
    lo3 = tuple(min(a[i], b[i]) for i in range(3))
    hi3 = tuple(max(a[i], b[i]) for i in range(3))
    if any(hi3[i] - lo3[i] < 0 for i in range(3)):
        return None
    return lo3, hi3


def arc_chord_polyline(arc: dict, p0: G.Pt3, p1: G.Pt3, *,
                       max_sagitta_mm: float = 25.0) -> tuple[list[G.Pt3], float]:
    """Дуга -> ломаная хорд + максимальная стрелка, которой её надо раздуть.

    Ревью №10: «хорда, раздутая на стрелку» не определена, пока не сказано, на
    сколько именно и в какую сторону. Здесь дуга режется на столько хорд,
    чтобы стрелка каждой не превышала названный порог, и возвращается ФАКТИЧЕСКАЯ
    стрелка — на неё раздувается оболочка. Дуги больше π режутся тем же
    правилом, без особого случая.
    """
    c = _pt3(arc.get("center_mm"))
    r = arc.get("radius_mm")
    a0, a1 = arc.get("start_angle_rad"), arc.get("end_angle_rad")
    xa, ya = _pt3(arc.get("x_axis")), _pt3(arc.get("y_axis"))
    if c is None or not G._finite(r) or r <= 0 or not G._finite(a0) \
            or not G._finite(a1) or xa is None or ya is None:
        return [p0, p1], 0.0
    span = abs(float(a1) - float(a0))
    if span <= G.EPS_MM:
        return [p0, p1], 0.0
    # n хорд -> стрелка суб-хорды r*(1-cos(span/2n)). ФОРМУЛА ВЕРНА ТОЛЬКО
    # ПОКА СУБ-ДУГА НЕ БОЛЬШЕ π: при span/n > π косинус разворачивается, и
    # условие «стрелка мала» проходит ЛОЖНО. Замер дыры (сверка с чек-листом
    # пар BHoM, где Circle — отдельный тип): при span ≈ 4π (715°…730°, 1440°)
    # n=1 давало cos(2π)=1, то есть sag=0, дуга подменялась ОДНОЙ хордой, и
    # тело уходило из оболочки на 5 900 мм при r=3000 — то же нарушение
    # закона консервативности, что и находка №1 закалки.
    #
    # Поэтому число хорд снизу ограничено ceil(span/π): суб-дуга НИКОГДА не
    # больше π, и формула применяется только в области своей применимости.
    n = max(1, math.ceil(span / math.pi))
    while n < 4096:
        sag = float(r) * (1.0 - math.cos(span / (2 * n)))
        if sag <= max_sagitta_mm:
            break
        n += 1
    pts: list[G.Pt3] = []
    for i in range(n + 1):
        ang = float(a0) + (float(a1) - float(a0)) * (i / n)
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        pts.append(tuple(c[k] + float(r) * (cos_a * xa[k] + sin_a * ya[k])
                         for k in range(3)))
    return pts, float(r) * (1.0 - math.cos(span / (2 * n)))


@dataclass(frozen=True)
class Section:
    """Прочитанное сечение: радиус оболочки и чем он обоснован."""
    radius_mm: float
    round: bool
    source: str
    #: outer | modelled | rect — чтения, содержащие тело. `nominal` сюда не
    #: попадает никогда: он возвращается отдельным полем `nominal_radius_mm`.
    kind: str = "rect"


def category_allows_sections(category: str) -> bool:
    """Разрешено ли КАТЕГОРИИ обосновывать оболочку сечением.

    Два условия сразу, и оба обязательны: правило чтения (`SECTION_RULES`) и
    разрешение таблицы (`sources`). Стена сегодня имеет число, но не имеет
    разрешения — и это запрет, а не отсутствие данных (ревью №2).
    """
    rule = KIND_TABLE.get(category)
    return (rule is not None and "axis_section" in rule.sources
            and category in SECTION_RULES)


def section_from_params(category: str, params: Any
                        ) -> tuple[Section | None, str, float | None]:
    """Сечение элемента из `params` строки L0.

    Возвращает `(Section|None, причина, номинальный радиус|None)`.

    Причина отсутствия НАЗЫВАЕТСЯ всегда: `no_section_rule` (категории сечение
    не разрешено), `section_absent` (чисел нет), `section_nominal_only`
    (число есть, но это НОМИНАЛ, а он тела не содержит — R3 красных).
    Молчаливого `None` не бывает.

    Номинал возвращается третьим элементом, а не выбрасывается: он остаётся в
    квитанции записи, чтобы «наружного нет» было отличимо от «сечения нет».

    Если читаются оба вида сечения (овальный воздуховод несёт и диаметр, и
    ширину с высотой), берётся БОЛЬШИЙ радиус: меньший мог бы не содержать
    тело, а огрубление законно только вверх.
    """
    if not category_allows_sections(category):
        return None, "no_section_rule", None
    rule = SECTION_RULES[category]
    p = params if isinstance(params, dict) else {}
    best: Section | None = None
    nominal: float | None = None

    def offer(cand: Section) -> None:
        nonlocal best
        if best is None or cand.radius_mm > best.radius_mm:
            best = cand

    for name in rule["round"]:
        d = p.get(name)
        if not (G._finite(d) and d > 0):
            continue
        kind = DIAMETER_KIND.get(name, "nominal")
        if kind in DIAMETER_KIND_ALLOWED:
            offer(Section(float(d) / 2.0, True, name, kind))
        else:
            # Номинал не строит оболочку НИКОГДА, но и не исчезает.
            r = float(d) / 2.0
            nominal = r if nominal is None else max(nominal, r)
    for w_name, h_name in rule["rect"]:
        w, h = p.get(w_name), p.get(h_name)
        if G._finite(w) and G._finite(h) and w > 0 and h > 0:
            offer(Section(math.hypot(float(w), float(h)) / 2.0, False,
                          f"{w_name}+{h_name}", "rect"))
    if best is None:
        return None, ("section_nominal_only" if nominal is not None
                      else "section_absent"), nominal
    return best, "", nominal


def carries_section_number(params: Any) -> bool:
    """Есть ли у элемента ХОТЬ ОДНО положительное число сечения в `params`.

    Нужно не оболочке, а переписи: стена с толщиной 200 мм и стена без неё —
    разные факты, даже когда обе получают габаритный бокс. Без этого счётчика
    «оболочки не поднялись» неотличимо от «параметры не читаются».
    """
    p = params if isinstance(params, dict) else {}
    return any(G._finite(p.get(n)) and p.get(n) > 0
               for n in ALL_SECTION_PARAM_NAMES)


def wall_prism_blockers(el: dict) -> tuple[str, ...]:
    """Чего НЕ ХВАТАЕТ, чтобы разрешить стене призму по одной толщине.

    Ревью кодекса №10: обычной прямой стене постоянной толщины суммарная
    ширина действительно достаточна, но L0 не умеет отличить её от
    slanted/tapered, stacked, vertically compound и стены со sweeps — а у
    каждой из этих призма по `width` НЕ содержит тело. Пока различить нельзя,
    честная оболочка одна: габаритный бокс.

    Функция возвращает ИМЕНА недостающих доказательств, а не bool: «нельзя»
    без причины — то же молчание, от которого закон переписи и защищает.
    """
    params = el.get("params") if isinstance(el.get("params"), dict) else {}
    return tuple(name for name in WALL_PRISM_EVIDENCE if name not in params)


#: `WALL_KEY_REF_PARAM` — какой ПЛОСКОСТЬЮ стены является её ось. Значения
#: перечисления Revit: 0 — осевая стены, 1 — осевая ядра, 2..5 — грани
#: (наружная/внутренняя отделки и ядра). Замер v18: у 213 из 215 стен-кандидатов
#: ось лежит на ГРАНИ (`3`), ещё у 2 — тоже грань (`2`). Ни одной осевой.
WALL_KEY_REF_CENTRELINE = 0


def wall_axis_halfwidth(width_mm: float, key_ref: Any) -> float:
    """Полуширина полосы вокруг оси, СОДЕРЖАЩЕЙ тело при любом ответе.

    Если ось — осевая стены (`key_ref == 0`), тело лежит в ±width/2, и это
    доказано. Во всех остальных случаях ось лежит на грани (или на осевой
    ЯДРА, которая при несимметричных слоях не совпадает с осевой стены), то
    есть тело смещено на одну сторону — а СТОРОНА в L0 не снята: знак зависит
    от ориентации стены, которой в артефакте нет.

    Угадывать сторону нельзя — ошибка знака сдвигает оболочку МИМО тела. Но
    содержать тело обязаны при любом ответе, а тело при любом смещении лежит
    внутри ±width от оси. Поэтому здесь ровно два исхода: доказанная осевая
    даёт width/2, всё остальное — width. Это огрубление вдвое, и оно
    НАЗВАНО, а не спрятано.
    """
    w = float(width_mm)
    return w / 2.0 if key_ref == WALL_KEY_REF_CENTRELINE else w


def hull_from_wall_axis(p0: G.Pt3, p1: G.Pt3, *, width_mm: float,
                        z0: float, z1: float,
                        offset_mm: float = 0.0) -> G.Prism | None:
    """Полоса вокруг оси стены × [z0, z1] — билдер БУДУЩЕЙ волны.

    Написан по требованию ревью №10 и НЕ ВЫЗЫВАЕТСЯ ни из одного пути:
    `OST_Walls` остаётся на `SOURCES_BBOX`, пока `wall_prism_blockers` не
    пуст. Здесь он живёт затем, чтобы день захвата `WALL_CROSS_SECTION` стоил
    одну строку в таблице, а не проектирования заново, и чтобы закон
    консервативности полосы был доказан ЗАРАНЕЕ, тестом.

    `offset_mm` — смещение тела относительно оси вдоль левой нормали (location
    line: грань вместо осевой). Оно ПРИНИМАЕТСЯ числом, а не выводится из
    `WALL_KEY_REF_PARAM`: знак зависит от ориентации стены, которой в L0 нет,
    и угадывать его значило бы сдвинуть оболочку в неверную сторону.
    """
    if not (G._finite(width_mm) and width_mm > 0):
        return None
    d = G._sub(p1, p0)
    L = math.hypot(d[0], d[1])
    if L <= G.EPS_MM:
        return None
    nx, ny = -d[1] / L, d[0] / L          # левая нормаль в плане
    half = float(width_mm) / 2.0
    cx, cy = nx * float(offset_mm), ny * float(offset_mm)
    corners = []
    for base in ((p0[0] + cx, p0[1] + cy), (p1[0] + cx, p1[1] + cy)):
        corners.append((base[0] + nx * half, base[1] + ny * half))
        corners.append((base[0] - nx * half, base[1] - ny * half))
    fp = G.convex_footprint(corners)
    if len(fp) < 3:
        return None
    lo, hi = (z0, z1) if z0 <= z1 else (z1, z0)
    return G.Prism(fp, lo, hi)


def _z_span(el: dict) -> tuple[float, float] | None:
    """Размах по Z, ОБЪЯВЛЕННЫЙ элементом, либо `None`.

    Существует затем, что у ЗАЯВЛЕНИЯ габаритного бокса нет вовсе: программа
    знает отметку уровня и высоту, но не знает, что из этого построит Revit.
    Разбор L0, наоборот, несёт настоящий габарит и этих ключей не имеет, —
    поэтому его поведение здесь не меняется ни на байт.
    """
    z0, z1 = el.get("z0_mm"), el.get("z1_mm")
    if not (G._finite(z0) and G._finite(z1)):
        return None
    lo, hi = float(z0), float(z1)
    return (lo, hi) if lo <= hi else (hi, lo)


#: Что обязано лежать в `el["prism"]`, чтобы полосу вокруг оси было ЧЕМ
#: обосновать. Список закрыт: недостающий ключ — названный откат в габарит,
#: а не повод «взять что есть».
PRISM_REQUIRED = ("width_mm", "uniform")


def _prism_record(el: dict, common: dict,
                  z_span: tuple[float, float] | None
                  ) -> tuple[HullRecord | None, str]:
    """Полоса вокруг оси стены. Возвращает `(запись|None, причина отката)`.

    ПОЧЕМУ СМЕЩЕНИЕ РОВНО НУЛЬ. Живой замер 28.07.2026 (Revit 2023, документ
    оператора, 700+ настоящих стен, `docs/2026-07-28-location-line-measurement.md`):
    тело стены СИММЕТРИЧНО `LocationCurve` при ЛЮБОМ ординале
    `WALL_KEY_REF_PARAM` — у стены 200 мм габарит по Y лежит в −100…+100, и
    ни один из шести ординалов не двигает ни кривую, ни тело. Поэтому здесь
    `width/2`, а не удвоение из `wall_axis_halfwidth`: удвоение защищает от
    НЕИЗВЕСТНОЙ стороны смещения, а у заявленной стены смещения нет — это
    измерено, а не предположено.
    """
    prism = el.get("prism")
    if not isinstance(prism, dict):
        return None, ""
    missing = [key for key in PRISM_REQUIRED if key not in prism]
    if missing:
        return None, "prism_incomplete_" + "+".join(sorted(missing))
    if not prism.get("uniform"):
        blockers = prism.get("blockers") or ()
        return None, ("prism_blocked_" + "+".join(sorted(str(b) for b in blockers))
                      if blockers else "prism_blocked")
    width = prism.get("width_mm")
    if not (G._finite(width) and width > 0):
        return None, "prism_width_invalid"
    if z_span is None:
        return None, "prism_z_span_missing"
    p0, p1 = _pt3(el.get("p0_mm")), _pt3(el.get("p1_mm"))
    if p0 is None or p1 is None:
        return None, "prism_endpoints_missing"
    hull = hull_from_wall_axis(p0, p1, width_mm=float(width),
                               z0=z_span[0], z1=z_span[1])
    if hull is None:
        return None, "prism_zero_length"
    extra = {"prism_width_mm": float(width),
             "prism_source": str(prism.get("source") or "")}
    return HullRecord(hull=hull, grade="conservative", hull_source="prism",
                      extra=extra, **common), ""


#: Виды кривых контура, которые оболочка умеет ОГРАНИЧИТЬ СНАРУЖИ. Список
#: закрыт: всё прочее (эллипс, сплайн, гиперболa) — названный отказ, потому
#: что доказанной наружной аппроксимации у нас для них нет.
PROFILE_CURVE_KINDS = ("line", "arc")


def _arc_outward_rect(p0: G.Pt2, p1: G.Pt2, mid: G.Pt2
                      ) -> tuple[float, G.Pt2] | str:
    """Стрелка дуги и НАРУЖНАЯ единичная нормаль хорды. Строка — отказ.

    ЗАЧЕМ. Хорда, проведённая по концам дуги, ВПИСАНА: тело лежит снаружи неё,
    и оболочка по хордам УМЕНЬШЕНА — ровно тот пропуск, за который `ревью №1`
    отправило все дуговые контуры в габаритный бокс (пол 9981227 фасада,
    середина дуги на 752.832 мм СНАРУЖИ «консервативной» оболочки).

    ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ. Пусть дуга опирается на хорду [p0,p1] и её середина
    отстоит от хорды на `s` (это и есть стрелка). Для дуги НЕ БОЛЬШЕ
    ПОЛУОКРУЖНОСТИ выполняются оба факта сразу:

      * проекция любой её точки на прямую хорды лежит между p0 и p1;
      * удаление любой её точки от прямой хорды не превосходит `s`.

    Значит дуга целиком лежит в ПРЯМОУГОЛЬНИКЕ «хорда × [0, s] в сторону
    середины». Заменяя ребро-хорду тремя сторонами этого прямоугольника,
    область РАСТЁТ и растёт СТРОГО НАРУЖУ — закон консервативности сохранён, а
    величина `s` не выдумана, а взята из данных (`arc_midpoints` разбора).

    ГРАНИЦА ПРИМЕНИМОСТИ ПРОВЕРЯЕТСЯ, А НЕ ПРЕДПОЛАГАЕТСЯ. `s >= L/2`
    равносильно «дуга не меньше полуокружности» (при полуугле θ: s = R(1−cosθ),
    L/2 = R·sinθ, и s ≥ L/2 ⟺ θ ≥ π/2). За этой границей первый факт неверен —
    дуга вылезает за торцы хорды, — и здесь честный отказ, а не формула вне
    своей области.
    """
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    if L <= G.EPS_MM:
        # Замкнутая дуга одним ребром: хорды нет, стрелку измерять не от чего.
        return "profile_arc_zero_chord"
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    sd = (mid[0] - p0[0]) * nx + (mid[1] - p0[1]) * ny
    s = abs(sd)
    if s <= G.EPS_MM:
        return "profile_arc_degenerate"      # дуга неотличима от прямой
    if 2.0 * s >= L:
        return "profile_arc_over_half_circle"
    return (s, (nx, ny) if sd > 0 else (-nx, -ny))


def profile_refusal(profile: dict) -> str | None:
    """Почему этому контуру НЕЛЬЗЯ верить. `None` — можно.

    Ревью №1, живой контрпример (пол 9981227 фасада, ребро 5 внешнего контура —
    дуга): овыпукление ОДНИХ ВЕРШИН заменяет дугу хордой, и середина дуги
    оказалась на 752.832 мм СНАРУЖИ «консервативной» оболочки. Закон
    консервативности нарушается на живых данных, то есть клеш можно пропустить.

    ВОЛНА DECOMPOSE снимает отказ ИМЕННО ДЛЯ ДУГ и только потому, что наружная
    аппроксимация теперь ДОКАЗАНА, а не обещана (`_arc_outward_rect`): дуга
    заменяется не хордой, а прямоугольником, который её содержит, и величина
    раздутия берётся из `arc_midpoints` разбора, а не из константы. Замер
    цены отказа (10.08.2026): у `демо-v3` дуга отправляла в габаритный бокс
    155 полов из 235 (66.0 %), у `k2_ar_rd_v15` — 57 из 398.

    Всё, что не прямая и не дуга, отказывается по-прежнему: наружной оболочки
    для сплайна у нас нет, а хорда по нему — тот же пропуск.
    """
    for loop in (profile.get("curve_kinds") or []):
        for kind in (loop or []):
            if kind and kind not in PROFILE_CURVE_KINDS:
                return f"profile_curve_{kind}"
    for name in ("exterior_loop",):
        for p in (profile.get(name) or []):
            if not (isinstance(p, (list, tuple)) and len(p) >= 2
                    and G._finite(p[0]) and G._finite(p[1])):
                return "profile_vertex_invalid"
    for hole in (profile.get("holes") or []):
        for p in (hole or []):
            if not (isinstance(p, (list, tuple)) and len(p) >= 2
                    and G._finite(p[0]) and G._finite(p[1])):
                return "profile_vertex_invalid"
    return None


@dataclass(frozen=True)
class ProfileRegion:
    """Разобранный контур: чем область ОБЪЯВЛЕНА, до всякой оболочки.

    Отдельный тип, а не кортеж, потому что полей стало четыре и они разной
    природы: петли — данные, накладки — вывод, габарит — доказательство,
    запас — замер огрубления. Кортеж из пяти позиций читается только
    сосчитыванием запятых.
    """
    #: Хордовые петли: первая внешняя, остальные — отверстия. НЕ ТРОНУТЫ.
    loops: tuple[tuple[G.Pt2, ...], ...] = ()
    #: Выпуклые накладки, накрывающие дуги. Объединяются с областью.
    arc_patches: tuple[tuple[G.Pt2, ...], ...] = ()
    #: ТОЧНЫЙ габарит объявленной области (вершины + крайние точки дуг).
    #: `None` — дуг нет, обрезать нечего.
    bounds: tuple[float, float, float, float] | None = None
    #: Наибольшая стрелка, на которую оболочка шире объявленного контура.
    arc_slack_mm: float = 0.0
    #: Почему контура нет. `None` — он есть.
    reason: str | None = None


def profile_loops(profile: dict) -> ProfileRegion:
    """Контуры профиля -> `ProfileRegion`.

    Петли возвращаются ХОРДОВЫМИ и НЕТРОНУТЫМИ; дуги едут отдельным списком
    ВЫПУКЛЫХ прямоугольников, которые потребитель ОБЪЕДИНЯЕТ с областью.

    ПОЧЕМУ ОТДЕЛЬНЫМ СПИСКОМ, А НЕ ВРЕЗКОЙ В ПЕТЛЮ. Первая версия вставляла
    две точки прямо в контур, разворачивая границу наружу по стрелке. На
    выпуклом контуре это работает, а на КОЛЬЦЕ — нет, и корпус такое кольцо
    предъявил: `k2_ar_rd_v15`, пол 11839990 — периметральная полоса шириной
    300 мм, у которой наружная и внутренняя границы едут ОДНОЙ петлёй в
    противоположных обходах. Врезка, добавлявшая площадь снаружи, на
    внутренней границе её ВЫЧИТАЛА: замер шейпли — 8 480 000 мм² настоящего
    материала пропало из оболочки, 524 пробы из 40 000 оказались вне тела.
    Это прямое нарушение закона содержания, то есть пропуск клеша.

    Объединение от ориентации не зависит вовсе: `A ∪ R ⊇ A` при любом обходе
    A и любом R. Куски вправе перекрываться — ни `signed_distance` (минимум по
    парам), ни `contains_point` (дизъюнкция по кускам) непересечения не
    требуют. Цена — до одной лишней ячейки на дугу.

    КОГДА НАКЛАДКА НЕ НУЖНА. Если середина дуги уже лежит В хордовой области,
    то и весь сегмент между хордой и дугой лежит в ней (сегмент связен и
    касается области только по хорде) — накрывать нечего. Проверка делается
    чёт-нечетом (`decompose.point_in_region`), который об ориентации ничего не
    знает; ошибиться в опасную сторону она не может, потому что лишняя
    накладка лишь ОГРУБЛЯЕТ, а пропущенная — нет.
    """
    raw = [profile.get("exterior_loop") or []]
    raw += [h or [] for h in (profile.get("holes") or [])]
    kinds = profile.get("curve_kinds") or []
    mids = profile.get("arc_midpoints") or []

    chord: list[list[G.Pt2]] = []
    for lp in raw:
        pts: list[G.Pt2] = []
        for p in lp:
            if not (isinstance(p, (list, tuple)) and len(p) >= 2
                    and G._finite(p[0]) and G._finite(p[1])):
                return ProfileRegion(reason="profile_vertex_invalid")
            pts.append((float(p[0]), float(p[1])))
        chord.append(pts)
    if not chord or len(chord[0]) < 3:
        return ProfileRegion(reason="profile_not_a_polygon")

    if not any(k == "arc" for lk in kinds for k in (lk or [])):
        return ProfileRegion(loops=tuple(tuple(c) for c in chord))

    if len(kinds) < len(chord):
        return ProfileRegion(reason="profile_curve_kinds_missing")
    rects: list[tuple[G.Pt2, ...]] = []
    extremes: list[G.Pt2] = []
    slack = 0.0
    for i, pts in enumerate(chord):
        lk = list(kinds[i] or [])
        lm = list(mids[i] or []) if i < len(mids) else []
        if len(lk) != len(pts):
            # Рёбер объявлено не столько, сколько вершин: сопоставить дугу с
            # ребром нечем, а угадывать соответствие — выдумывать геометрию.
            return ProfileRegion(reason="profile_curve_kinds_mismatch")
        n = len(pts)
        for j in range(n):
            if lk[j] != "arc":
                continue
            p0, p1 = pts[j], pts[(j + 1) % n]
            m = lm[j] if j < len(lm) else None
            if not (isinstance(m, (list, tuple)) and len(m) >= 2
                    and G._finite(m[0]) and G._finite(m[1])):
                return ProfileRegion(reason="profile_arc_midpoint_missing")
            mid = (float(m[0]), float(m[1]))
            if D.point_in_region(mid, chord):
                continue                     # хорда уже накрывает сегмент
            got = _arc_outward_rect(p0, p1, mid)
            if isinstance(got, str):
                return ProfileRegion(reason=got)
            s, nrm = got
            rects.append((p0, p1,
                          (p1[0] + nrm[0] * s, p1[1] + nrm[1] * s),
                          (p0[0] + nrm[0] * s, p0[1] + nrm[1] * s)))
            extremes.extend(arc_extremes(p0, p1, mid))
            if s > slack:
                slack = s
    pts_all = [q for lp in chord for q in lp] + extremes
    bounds = (min(q[0] for q in pts_all), min(q[1] for q in pts_all),
              max(q[0] for q in pts_all), max(q[1] for q in pts_all))
    return ProfileRegion(loops=tuple(tuple(c) for c in chord),
                         arc_patches=tuple(rects), bounds=bounds,
                         arc_slack_mm=slack)


def _circle_through(p0: G.Pt2, m: G.Pt2, p1: G.Pt2) -> tuple[G.Pt2, float] | None:
    """Окружность по трём точкам. `None` — точки коллинеарны."""
    ax, ay = p0
    bx, by = m
    cx, cy = p1
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if d == 0.0:
        return None
    sa, sb, sc = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (sa * (by - cy) + sb * (cy - ay) + sc * (ay - by)) / d
    uy = (sa * (cx - bx) + sb * (ax - cx) + sc * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def arc_extremes(p0: G.Pt2, p1: G.Pt2, mid: G.Pt2) -> list[G.Pt2]:
    """Крайние по осям точки ДУГИ — точно, а не по её вершинам.

    Габарит дуги не равен габариту её концов: у дуги, перевалившей через
    направление оси, крайняя точка лежит ВНУТРИ пролёта. Считается это без
    единого допуска: окружность восстанавливается по трём объявленным точкам
    (начало, середина, конец), и каждая из четырёх осевых точек окружности
    включается тогда и только тогда, когда лежит НА дуге.
    """
    got = _circle_through(p0, mid, p1)
    if got is None:
        return [p0, p1, mid]
    (cx, cy), r = got
    if not (math.isfinite(cx) and math.isfinite(cy) and math.isfinite(r)):
        return [p0, p1, mid]
    tau = 2.0 * math.pi
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    am = math.atan2(mid[1] - cy, mid[0] - cx)
    a1 = math.atan2(p1[1] - cy, p1[0] - cx)
    span_m = (am - a0) % tau
    span_1 = (a1 - a0) % tau
    ccw = span_m <= span_1          # обход, при котором середина лежит внутри
    out = [p0, p1, mid]
    for k in range(4):
        ang = k * math.pi / 2.0
        rel = (ang - a0) % tau if ccw else (a0 - ang) % tau
        lim = span_1 if ccw else (a0 - a1) % tau
        if rel <= lim:
            out.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return out


def hull_from_region(loops: Sequence[Sequence[G.Pt2]], z0: float, z1: float,
                     clip_xy: tuple[float, float, float, float] | None = None,
                     arc_rects: Sequence[Sequence[G.Pt2]] = ()
                     ) -> tuple[G.Hull | None, dict]:
    """Область подошвы × [z0, z1] -> оболочка и КВИТАНЦИЯ о том, как она вышла.

    Три исхода, и все три названы:

    * контур ВЫПУКЛЫЙ и без отверстий — прежняя `Prism` с прежней подошвой,
      байт-в-байт. Уточнять нечего, а сдвигать отчёт там, где геометрия не
      изменилась, значит сделать диф волны нечитаемым;
    * разбивка сошлась — `PrismSet` из выпуклых кусков, объединение которых
      РАВНО объявленной области (доказано в `decompose`);
    * разбивка отказалась — прежняя выпуклая призма с засыпанными отверстиями,
      но причина отказа едет в квитанции. Молчаливого овыпукления не бывает:
      без имени «оболочка выпуклая» неотличимо от «оболочка выпуклая, потому
      что мы сдались», а это разные факты о поиске.
    """
    if not loops:
        return None, {"reason": "profile_not_a_polygon"}
    ext = list(loops[0])
    holes = [list(h) for h in loops[1:] if h and len(h) >= 3]
    lo, hi = (z0, z1) if z0 <= z1 else (z1, z0)

    form: dict = {}
    cells: tuple[tuple[G.Pt2, ...], ...]
    if not holes and not arc_rects and D.loop_is_convex(ext):
        fp = G.convex_footprint(ext)
        if len(fp) < 3:
            return None, {"reason": "profile_not_a_polygon"}
        cells, form = (fp,), {"footprint_form": "convex_loop"}
    else:
        dec = D.decompose(ext, holes)
        if dec.ok:
            cells = dec.cells
            form = {"footprint_form": "decomposed", "holes_carved": len(holes)}
        else:
            fp = G.convex_footprint(ext)
            if len(fp) < 3:
                return None, {"reason": "profile_not_a_polygon"}
            cells = (fp,)
            form = {"footprint_form": "convexified",
                    "holes_filled": len(holes),
                    "decomposition_refused": dec.reason,
                    **{f"decomposition_{k}": v
                       for k, v in (dec.stats or {}).items()
                       if k in ("cells", "slabs", "work", "residual_rel")}}

    # Накладки на дуги ОБЪЕДИНЯЮТСЯ с областью, а не врезаются в контур: см.
    # `profile_loops`. Каждая накладка уже выпукла, поэтому это просто ещё
    # куски; перекрытие с соседями законно и ничему не мешает.
    if arc_rects:
        cells = tuple(cells) + tuple(tuple(r) for r in arc_rects)
        form["arc_patches"] = len(arc_rects)

    # Обрезка по габариту — ОДНА на все три исхода, а не только на разбивку.
    # Отдельная обрезка у одного исхода была бы ровно тем классом дефекта,
    # что чинится в этом модуле весь месяц: правило, работающее на одной ветке
    # и молчащее на соседней. Замер, который это поймал (10.08.2026,
    # `k2_ar_rd_v15`): 138 находок, которых до волны не было, приходили с
    # ветки `convexified` — там выпуклая оболочка бралась от УЖЕ РАЗДУТОГО
    # дугами контура и наружные углы дуг за габарит никто не срезал.
    cells, clipped_frac = _clip_cells(cells, clip_xy)
    if not cells:
        return None, {"reason": "profile_not_a_polygon"}
    form["footprint_cells"] = len(cells)
    if clipped_frac > 0.0:
        form["bbox_clip_removed_frac"] = round(clipped_frac, 9)
    if len(cells) == 1:
        return G.Prism(cells[0], lo, hi), form
    return G.PrismSet(cells, lo, hi), form


def _clip_cells(cells: Sequence[Sequence[G.Pt2]],
                clip_xy: tuple[float, float, float, float] | None
                ) -> tuple[tuple[tuple[G.Pt2, ...], ...], float]:
    """Ячейки ∩ СОБСТВЕННЫЙ габарит области. Плюс срезанная доля.

    ПОЧЕМУ НЕ ГАБАРИТ ЭЛЕМЕНТА, ХОТЯ ИМЕННО ОН НАПРАШИВАЛСЯ. Габарит Revit
    содержит тело — рассуждение верное и неприменимое: контур и габарит
    приезжают из разбора РАЗНЫМИ путями и в корпусе расходятся. Замер
    10.08.2026, `snowdon_plumb_v5`, пол 1424071: объявленный контур доходит до
    x = 974.73, а габарит элемента заканчивается на x = −1854.20, и обрезка по
    габариту вырезала 21.13 % ОБЪЯВЛЕННОЙ области. Проба вложенности поймала
    это как 95 точек контура вне оболочки — то есть как ПРОПУСК КЛЕША, а не
    как неточность.

    Обрезается поэтому по габариту САМОЙ ОБЛАСТИ (вершины контуров плюс ТОЧНЫЕ
    крайние точки дуг, `arc_extremes`). Такой габарит содержит область по
    построению, поэтому обрезка не может отнять ни одной её точки — она может
    отнять только УГЛЫ НАКЛАДОК, которые торчат за пределы всего, что вообще
    объявлено. Ни одного допуска и ни одной веры в чужую рамку здесь больше
    нет, и сторож `MAX_BBOX_CLIP_FRAC` вместе с ними не нужен: отнимать
    нечего.
    """
    if clip_xy is None:
        return tuple(tuple(c) for c in cells), 0.0
    x0, y0, x1, y1 = clip_xy
    total = sum(D.polygon_area(c) for c in cells if len(c) >= 3)
    out: list[tuple[G.Pt2, ...]] = []
    kept_area = 0.0
    for c in cells:
        q = D.clip_to_box(c, x0, y0, x1, y1)
        if not q:
            continue
        out.append(q)
        if len(q) >= 3:
            kept_area += D.polygon_area(q)
    if not out or total <= 0.0:
        return tuple(tuple(c) for c in cells), 0.0
    return tuple(out), max(0.0, (total - kept_area) / total)


def hull_from_profile(loop: list, z0: float, z1: float) -> G.Hull | None:
    """Один контур подошвы -> оболочка. Тонкая обёртка над `hull_from_region`.

    Отверстий у этого входа нет по определению, дуг — тоже (вызывающий уже
    прошёл `profile_refusal`). Вогнутость больше НЕ овыпукляется: она
    раскладывается на выпуклые куски, и оболочка становится равна контуру, а
    не его выпуклой оболочке.
    """
    pts: list[G.Pt2] = []
    for p in loop:
        if not (isinstance(p, (list, tuple)) and len(p) >= 2
                and G._finite(p[0]) and G._finite(p[1])):
            return None                      # молча не выбрасываем — отказываем
        pts.append((float(p[0]), float(p[1])))
    if len(pts) < 3:
        return None
    return hull_from_region((pts,), z0, z1)[0]


def build_hull(el: dict, *, profile: dict | None = None,
               curve: dict | None = None) -> tuple[HullRecord | None, Refusal | None]:
    """Единственная точка, где элемент превращается в оболочку.

    Порядок источников — от точного к грубому, и он же определяет грейд.
    Ни один шаг не ДОДУМЫВАЕТ числа: сечения и толщины берутся только из
    данных, а когда их нет — оболочкой становится габаритный бокс, который в
    данных есть всегда.
    """
    sid = str(el.get("element_id"))
    cat = el.get("category") or "?"
    rule = KIND_TABLE.get(cat)
    if rule is None:
        return None, Refusal(sid, cat, "unsupported", "kind_outside_table")
    if not rule.eligible:
        return None, Refusal(sid, cat, "not_eligible", rule.note or "нет тела")

    box = _valid_box(el.get("bbox_min_mm"), el.get("bbox_max_mm"))
    common = dict(source_id=sid, category=cat, label=rule.label,
                  mvp_side=rule.mvp_side, level_id=el.get("level_id"),
                  type_name=el.get("type_name"))
    #: Почему более точный источник не сработал. Пустой список = сработал первый.
    downgrades: list[str] = []
    #: Размах по Z, ОБЪЯВЛЕННЫЙ источником (программа знает отметку уровня и
    #: высоту; у разбора L0 его нет — там Z приходит из настоящего габарита).
    z_span = _z_span(el) or (None if box is None else (box[0][2], box[1][2]))

    # 0. Полоса вокруг оси × [z0, z1] — стена. Числа приходят целиком из
    #    `el["prism"]`, и билдер НИЧЕГО не достраивает: неполный набор — это
    #    названный откат, а не «взяли что было».
    if "prism" in rule.sources:
        pr_rec, why = _prism_record(el, common, z_span)
        if pr_rec is not None:
            return pr_rec, None
        if why:
            downgrades.append(why)

    # 1. Контур подошвы (перекрытия, кровли) — призма. Только если КАТЕГОРИИ
    #    этот источник разрешён (ревью №12) и контуру можно верить (ревью №1).
    if ("profile" in rule.sources and profile
            and profile.get("profile_available") and z_span):
        why = profile_refusal(profile)
        if why is None:
            reg = profile_loops(profile)
            if reg.reason is not None:
                downgrades.append(reg.reason)
            else:
                loops, arc_rects, arc_slack = (
                    reg.loops, reg.arc_patches, reg.arc_slack_mm)
                # Обрезка нужна ровно там, где есть накладки на дуги: только
                # их углы и умеют вылезти за пределы объявленного. Границей
                # служит габарит САМОЙ области, а не элемента (см. `_clip_cells`).
                clip = reg.bounds if arc_rects else None
                pr, receipt = hull_from_region(loops, z_span[0], z_span[1],
                                               clip_xy=clip, arc_rects=arc_rects)
                if pr is not None:
                    extra = dict(receipt)
                    extra["holes_declared"] = len(profile.get("holes") or [])
                    if arc_slack > 0.0:
                        # Насколько оболочка ШИРЕ объявленного контура из-за
                        # дуг. Число считается по геометрии самой дуги, а не
                        # берётся из константы допуска, — иначе «наружная
                        # аппроксимация» была бы обещанием, а не замером.
                        extra["arc_outward_slack_mm"] = round(arc_slack, 6)
                    if downgrades:
                        extra["downgraded_from"] = list(downgrades)
                    return HullRecord(hull=pr, grade="conservative",
                                      hull_source="profile",
                                      extra=extra, **common), None
                downgrades.append(receipt.get("reason") or "profile_not_a_polygon")
        else:
            downgrades.append(why)

    # 2. Ось + СЕЧЕНИЕ ИЗ ДАННЫХ — капсула. Числа приходят из `params` строки
    #    L0 (эмиссия d154196e): ключ params равен имени BuiltInParameter.
    #    Поле `section_radius_mm` остаётся старшим входом — им пользуются
    #    синтетические сцены и снапшоты из других источников.
    radius: Any = None
    round_flag: Any = None
    section_source: str | None = None
    nominal_radius: float | None = None
    if "axis_section" in rule.sources:
        radius, round_flag = el.get("section_radius_mm"), el.get("section_round")
        if G._finite(radius) and radius > 0:
            section_source = "section_radius_mm"
        else:
            sec, why, nominal_radius = section_from_params(cat, el.get("params"))
            if sec is not None:
                radius, round_flag, section_source = (
                    sec.radius_mm, sec.round, sec.source)
            elif why in ("section_absent", "section_nominal_only"):
                # Категории источник разрешён, доказанного числа нет — это
                # НАЗВАННЫЙ откат, а не «так и было». Без имени грейд coarse
                # у целого раздела неотличим от сломанного чтения параметров.
                downgrades.append(why)
    common["section_radius_mm"] = (
        float(radius) if section_source is not None else None)
    common["section_round"] = (
        bool(round_flag) if section_source is not None else None)
    common["section_source"] = section_source

    def _extra(base: dict | None = None) -> dict:
        """Квитанция записи. Номинал попадает сюда ВСЕГДА, когда он прочитан:
        «наружного нет» и «сечения нет» — разные диагнозы (R3 красных)."""
        out = dict(base or {})
        if downgrades:
            out["downgraded_from"] = list(downgrades)
        if nominal_radius is not None:
            out["nominal_radius_mm"] = float(nominal_radius)
        return out
    if section_source is not None:
        path = None
        if curve and curve.get("curve_kind") == "arc":
            arc = curve.get("arc") or {}
            p0a, p1a = _pt3(curve.get("p0_mm")), _pt3(curve.get("p1_mm"))
            if p0a is None or p1a is None:
                # Ревью №4: битая дуга возвращала [p0,p1], а без точек —
                # (0,0,0), то есть оболочку в начале координат.
                downgrades.append("arc_endpoints_missing")
            else:
                pts, sag = arc_chord_polyline(arc, p0a, p1a)
                if sag <= 0 and len(pts) == 2:
                    downgrades.append("arc_unreadable")
                else:
                    path, radius = pts, float(radius) + sag
        else:
            p0 = _pt3(el.get("p0_mm")) or _pt3((curve or {}).get("p0_mm"))
            p1 = _pt3(el.get("p1_mm")) or _pt3((curve or {}).get("p1_mm"))
            if p0 is None or p1 is None:
                downgrades.append("axis_endpoints_missing")
            elif G._len(G._sub(p1, p0)) <= G.EPS_MM:
                # Ревью №4: нулевая длина превращала трубу в СФЕРУ радиуса
                # сечения — тело, которого в модели нет.
                downgrades.append("axis_zero_length")
            else:
                path = [p0, p1]
        if path:
            # Ревью №4: `exact` не бывает у капсулы НИКОГДА. У прямой трубы
            # торцы плоские, у капсулы — сферические; дуговая капсула вдобавок
            # раздута стрелкой. `exact` читается вердиктом `confirmed`, то есть
            # обвинением, которое оболочка не доказывает.
            return HullRecord(hull=G.Capsule(tuple(path), float(radius)),
                              grade="conservative", hull_source="axis_section",
                              extra=_extra(), **common), None

    # 3. Габаритный бокс — есть про каждый извлечённый элемент.
    if box:
        return HullRecord(hull=G.Aabb(box[0], box[1]), grade="coarse",
                          hull_source="bbox",
                          extra=_extra(), **common), None

    return None, Refusal(sid, cat, "missing_geometry",
                         "нет ни контура, ни сечения, ни габаритного бокса")



#: КАКОЙ ИСТОЧНИК какой грейд выдаёт. Таблица не описательная, а проверяемая:
#: `grade_reachability()` сверяет её с `KIND_TABLE` и объявляет НЕДОСТИЖИМЫМ
#: тот грейд, которому не осталось ни одного источника ни у одной категории.
#: Без такой сверки «exact = 0» в отчёте читается как «точных оболочек не
#: нашлось», хотя на самом деле их не может быть в принципе.
GRADE_BY_SOURCE: dict[str, str] = {
    "prism": "conservative",
    "profile": "conservative",
    "axis_section": "conservative",
    "bbox": "coarse",
}

#: Почему грейд недостижим. Ключ обязан быть в `GRADES`; пустой словарь
#: означал бы, что достижимо всё, и это утверждение тоже проверяется.
UNREACHABLE_GRADE_REASONS: dict[str, str] = {
    "exact": (
        "`exact` значит ОБОЛОЧКА РАВНА ТЕЛУ, и сегодня этого не доказывает ни "
        "один источник: у капсулы прямой трубы торцы СФЕРИЧЕСКИЕ вместо "
        "плоских (ревью №4), а габаритный бокс телом не является по "
        "определению. Замер 10.08.2026 по всему складу: 65 читаемых прогонов, "
        "664 870 оболочек, `exact` = 0 — то есть недостижимость не наблюдение "
        "на выборке, а свойство таблицы источников. "
        "ВОЛНА DECOMPOSE ЗАКРЫЛА ОДНО ИЗ ТРЁХ УСЛОВИЙ И НЕ ПОДПИСЫВАЕТ ГРЕЙД. "
        "Подошва источника `profile` с этой волны РАВНА объявленному контуру "
        "(разбивка на выпуклые куски, отверстия вырезаны, сверка площадей "
        "сходится) — это условие ВЫПОЛНЕНО. Не выполнены два других, и оба "
        "названы: (1) РАЗМАХ ПО Z берётся как [z0, z1] из объявленной отметки "
        "и толщины, а НАПРАВЛЕНИЯ РОСТА тела в снапшоте нет — плита в 200 мм "
        "с отметкой 3000 может занимать и [2800,3000], и [3000,3200], и "
        "оболочка обязана накрывать обе догадки; (2) ДУГА раздувается наружу "
        "на стрелку, то есть оболочка СТРОГО ШИРЕ тела ровно на "
        "`arc_outward_slack_mm`, и это огрубление, пусть и измеренное. "
        "Подписать `exact` по одной закрытой оси из трёх значило бы повторить "
        "дефект, который в этом модуле только что чинили: подпись на оси, "
        "которую никто не прочитал."
    ),
}


def grade_reachability() -> dict[str, dict]:
    """Достижим ли каждый грейд — ВЫВОДОМ из таблицы, а не наблюдением.

    Отчёт, печатающий `exact: 0`, не отличает «точных оболочек не нашлось» от
    «точных оболочек не бывает». Разница решает, читать ли `confirmed` как
    отсутствующий факт или как несуществующую ось.
    """
    live: set[str] = set()
    for rule in KIND_TABLE.values():
        if not rule.eligible:
            continue
        for src in rule.sources:
            g = GRADE_BY_SOURCE.get(src)
            if g:
                live.add(g)
    return {
        g: {"reachable": g in live,
            "emitting_sources": sorted(s for s, gg in GRADE_BY_SOURCE.items()
                                       if gg == g),
            "reason": "" if g in live else UNREACHABLE_GRADE_REASONS.get(
                g, "источника нет, причина не названа — это дефект таблицы")}
        for g in GRADES}

def coverage_matrix() -> list[dict]:
    """Закрытая матрица для отчёта: категория → пригодность → класс → грейды."""
    rows = []
    for cat, rule in sorted(KIND_TABLE.items()):
        rows.append({
            "category": cat,
            "eligible": rule.eligible,
            "mvp_side": rule.mvp_side,
            "label": rule.label,
            "hull_sources": list(rule.sources) if rule.eligible else [],
            "refusal": "" if rule.eligible else (rule.note or "нет тела"),
        })
    return rows
