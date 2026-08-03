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
from typing import Any

from kukai.clash import geom as G

#: Грейд оболочки — насколько она обжимает элемент.
#:
#: `exact`        — оболочка совпадает с телом (прямая труба круглого сечения);
#: `conservative` — содержит тело и огрубляет НАЗВАННЫМ образом (контур с
#:                  засыпанными отверстиями, дуга по хорде+стрелке);
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
    # Стена — только габарит: wall-builder (полоса вокруг оси × [z0,z1]) не
    # построен, а универсальная капсула вокруг НИЖНЕЙ оси не покрывает высоту
    # (ревью №2). Пока его нет, разрешать стене ось — значит разрешать пропуск.
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


def profile_refusal(profile: dict) -> str | None:
    """Почему этому контуру НЕЛЬЗЯ верить. `None` — можно.

    Ревью №1, живой контрпример (пол 9981227 фасада, ребро 5 внешнего контура —
    дуга): овыпукление ОДНИХ ВЕРШИН заменяет дугу хордой, и середина дуги
    оказалась на 752.832 мм СНАРУЖИ «консервативной» оболочки. Закон
    консервативности нарушается на живых данных, то есть клеш можно пропустить.

    Доказанной наружной аппроксимации дуги в D1 нет, поэтому здесь принят
    единственный честный исход: любая дуга или любая невалидная вершина —
    ОТКАЗ от контура, откат в габаритный бокс. Бокс грубее, но содержит тело;
    хорда — нет.
    """
    for loop in (profile.get("curve_kinds") or []):
        for kind in (loop or []):
            if kind and kind != "line":
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


def hull_from_profile(loop: list, z0: float, z1: float) -> G.Prism | None:
    """Контур подошвы -> призма. Отверстия ЗАСЫПАЮТСЯ, контур овыпукляется —
    и то и другое увеличивает оболочку, то есть законно по закону
    консервативности; именно поэтому грейд `conservative`, а не `exact`.

    Вызывать только после `profile_refusal(...) is None`: молчаливый выброс
    невалидной вершины УМЕНЬШАЕТ оболочку, а это уже не огрубление.
    """
    pts = []
    for p in loop:
        if not (isinstance(p, (list, tuple)) and len(p) >= 2
                and G._finite(p[0]) and G._finite(p[1])):
            return None                      # молча не выбрасываем — отказываем
        pts.append((float(p[0]), float(p[1])))
    if len(pts) < 3:
        return None
    fp = G.convex_footprint(pts)
    if len(fp) < 3:
        return None
    lo, hi = (z0, z1) if z0 <= z1 else (z1, z0)
    return G.Prism(fp, lo, hi)


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

    # 1. Контур подошвы (перекрытия, кровли) — призма. Только если КАТЕГОРИИ
    #    этот источник разрешён (ревью №12) и контуру можно верить (ревью №1).
    if "profile" in rule.sources and profile and profile.get("profile_available") and box:
        why = profile_refusal(profile)
        if why is None:
            pr = hull_from_profile(profile.get("exterior_loop") or [],
                                   box[0][2], box[1][2])
            if pr is not None:
                return HullRecord(hull=pr, grade="conservative",
                                  hull_source="profile",
                                  extra={"holes_filled": len(profile.get("holes") or [])},
                                  **common), None
            downgrades.append("profile_not_a_polygon")
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
