"""КР — Конструкции: curated leaves for СП 63.13330.2018 (монолит ЖБ),
СП 16.13330.2017 (сталь), СП 20.13330.2016 (нагрузки).

Every leaf here is Ярус 2 (requirement=None + check_question_ru). This is NOT a
shortcut — it is the honest state of the extractor: the fixed Ярус-1 fact set
(room/door/window/wall/stair, each carrying only area_m2/height_m/width_m/...)
has no key for any quantity a КР check actually needs (защитный слой в мм,
диаметр стержня, коэффициент армирования, гибкость, прогиб, шаг стержней).
Forcing a Ярус-1 Requirement onto a nonexistent fact would silently produce
``not_evaluated`` forever, or worse, quietly bind to the wrong key — so every
leaf stays Ярус 2 until the C# extractor (kukai.norm_control.MODEL_FACTS_CS)
grows the corresponding element_kind/param. See the extractor-extension list
in the curation report (not fabricated here — real BuiltInParameter names
where they exist, honestly flagged as "derived, no direct parameter" where
they don't).

Every citation_anchor below is verified against the real data/norms.db by
kukai.norm_control.ground_citation (see tests/test_norm_tree.py's grounding
invariant once this module is wired into norm_tree.ROOT).
"""
from __future__ import annotations

from kukai.norm_tree import NormLeaf

_SP63 = "СП 63.13330.2018"   # Бетонные и железобетонные конструкции
_SP16 = "СП 16.13330.2017"   # Стальные конструкции
_SP20 = "СП 20.13330.2016"   # Нагрузки и воздействия


LEAVES: list[NormLeaf] = [

    # ── СП 63.13330.2018 — монолит ЖБ ────────────────────────────────────────

    NormLeaf(
        id="kr.monolith.rebar_cover_indoor",
        title_ru="Толщина защитного слоя бетона — закрытые помещения",
        element_kind="rebar",  # NEW extractor kind — see report
        categories=("OST_Rebar",),
        norm_doc=_SP63,
        coarse_kw="закрытых помещениях",
        citation_anchor="В закрытых помещениях при нормальной и пониженной влажности 20",
        topic_keywords=("защитный слой", "защитного слоя", "покрытие арматуры", "cover"),
        check_question_ru=(
            "Толщина защитного слоя бетона рабочей арматуры в закрытых помещениях при "
            "нормальной/пониженной влажности — не менее 20 мм (Таблица 10.1, п.10.3.2 СП63; "
            "повышенная влажность — 25 мм, открытый воздух — 30 мм, грунт с бетонной "
            "подготовкой — 40 мм, без подготовки — 70 мм; для сборных элементов -5 мм, для "
            "конструктивной арматуры -5 мм от указанных значений). Проверь фактический cover "
            "арматуры против применимой строки таблицы для условий эксплуатации конструкции."
        ),
        severity="review",
    ),
    NormLeaf(
        id="kr.monolith.rebar_cover_min_absolute",
        title_ru="Абсолютный минимум защитного слоя бетона",
        element_kind="rebar",
        categories=("OST_Rebar",),
        norm_doc=_SP63,
        coarse_kw="диаметра стержня арматуры",
        citation_anchor="не менее диаметра стержня арматуры и не менее 10 мм",
        topic_keywords=("защитный слой", "диаметр арматуры", "минимальный защитный слой"),
        check_question_ru=(
            "Независимо от Таблицы 10.1, толщину защитного слоя бетона всегда следует "
            "принимать не менее диаметра стержня арматуры и не менее 10 мм (п.10.3.2 СП63). "
            "Проверь: cover_mm >= max(rebar_diameter_mm, 10)."
        ),
        severity="review",
    ),
    NormLeaf(
        id="kr.monolith.min_reinforcement_ratio",
        title_ru="Минимальный процент армирования",
        element_kind="column",  # also applies to beam/slab — see report
        categories=("OST_StructuralColumns", "OST_StructuralFraming", "OST_Floors"),
        norm_doc=_SP63,
        coarse_kw="10.3.6",
        citation_anchor="принимать не менее: 0,1% - в изгибаемых, внецентренно растянутых элементах",
        topic_keywords=("процент армирования", "коэффициент армирования", "минимальное армирование"),
        check_question_ru=(
            "Площадь сечения продольной арматуры (в % от рабочей площади бетонного сечения) "
            "должна быть не менее 0,1% в изгибаемых/внецентренно-растянутых/внецентренно-сжатых "
            "элементах при гибкости <=17 (<=5 для прямоугольных сечений), и не менее 0,25% во "
            "внецентренно-сжатых элементах при гибкости >=87 (>=25 для прямоугольных); для "
            "промежуточной гибкости — линейная интерполяция; при арматуре по контуру сечения или "
            "в центрально-растянутых элементах — вдвое больше (п.10.3.6 СП63). Элементы, не "
            "удовлетворяющие минимуму, относят к бетонным (не железобетонным). Проверь заявленный "
            "коэффициент армирования против применимого порога."
        ),
        severity="review",
    ),
    NormLeaf(
        id="kr.monolith.column_slenderness_limit",
        title_ru="Предельная гибкость сжатых элементов (ЖБ)",
        element_kind="column",
        categories=("OST_StructuralColumns",),
        norm_doc=_SP63,
        coarse_kw="10.2.2",
        citation_anchor=(
            "200 - для железобетонных элементов; 120 - для колонн, являющихся элементами "
            "зданий; 90 - для бетонных элементов"
        ),
        topic_keywords=("гибкость", "предельная гибкость", "гибкость колонны"),
        check_question_ru=(
            "Гибкость (l0/i) внецентренно сжатого элемента в любом направлении не должна "
            "превышать: 200 — для железобетонных элементов вообще, 120 — для колонн, являющихся "
            "элементами зданий, 90 — для бетонных (неармированных) элементов (п.10.2.2 СП63). "
            "Проверь гибкость колонны против применимого из трёх порогов."
        ),
        severity="review",
    ),
    NormLeaf(
        id="kr.monolith.rebar_spacing_max",
        title_ru="Максимальный шаг стержней продольной арматуры",
        element_kind="beam",  # also column/slab/wall — see report
        categories=("OST_StructuralFraming", "OST_Floors", "OST_StructuralColumns", "OST_Walls"),
        norm_doc=_SP63,
        coarse_kw="10.3.8",
        citation_anchor="наибольшие расстояния между осями стержней продольной арматуры",
        topic_keywords=("шаг арматуры", "расстояние между стержнями", "шаг стержней"),
        check_question_ru=(
            "П.10.3.8 СП63 ограничивает наибольшие расстояния между осями стержней продольной "
            "арматуры в балках, плитах, колоннах и стенах (порядка 200-500 мм в зависимости от "
            "типа элемента и высоты сечения; в стенах — не более 2*толщина_стены и 400 мм по "
            "вертикали, 400 мм по горизонтали). ВНИМАНИЕ: цифровая часть таблицы повреждена в "
            "OCR-извлечении из norms.db (см. citation) — перед автоматической проверкой сверь "
            "точные пороги с оригиналом СП63 п.10.3.8, не доверяй голым цифрам из индекса."
        ),
        severity="review",
    ),
    NormLeaf(
        id="kr.monolith.deflection_reference_sp20",
        title_ru="Предельные прогибы ЖБ элементов — отсылка к СП20",
        element_kind="beam",
        categories=("OST_StructuralFraming", "OST_Floors"),
        norm_doc=_SP63,
        coarse_kw="8.2.20",
        citation_anchor="Значения предельно допустимых деформаций элементов принимают согласно СП 20.13330",
        topic_keywords=("прогиб", "предельный прогиб", "деформация"),
        check_question_ru=(
            "П.8.2.20 СП63 требует принимать предельно допустимые прогибы железобетонных "
            "элементов согласно СП 20.13330 (и нормативным документам на конкретные виды "
            "конструкций) — см. leaf kr.loads.deflection_default_limit для конкретного порога. "
            "Проверь фактический прогиб элемента (мм) против предельного значения из СП20, "
            "применимого к его типу и пролёту."
        ),
        severity="review",
    ),

    # ── СП 20.13330.2016 — нагрузки (прогибы/перемещения) ───────────────────

    NormLeaf(
        id="kr.loads.deflection_default_limit",
        title_ru="Предельный прогиб — общий случай (не оговорённый отдельно)",
        element_kind="beam",
        categories=("OST_StructuralFraming", "OST_Floors"),
        norm_doc=_SP20,
        coarse_kw="15.2.3",
        citation_anchor="не должны превышать 1/150 пролета или 1/75 вылета консоли",
        topic_keywords=("предельный прогиб", "прогиб", "деформация", "1/150", "1/75"),
        check_question_ru=(
            "Для элементов конструкций, чьи предельные прогибы не оговорены отдельно (Таблица "
            "Д.1 приложения Д СП20) или другими нормативными документами, вертикальные и "
            "горизонтальные прогибы/перемещения от постоянных+длительных+кратковременных "
            "нагрузок не должны превышать 1/150 пролёта (балки/плиты) или 1/75 вылета консоли "
            "(п.15.2.3 СП20). Проверь: deflection_mm / span_mm <= 1/150 (или <= 1/75 для "
            "консоли)."
        ),
        severity="review",
    ),
    NormLeaf(
        id="kr.loads.roof_slope_min",
        title_ru="Минимальный уклон кровли (по условию прогиба настила)",
        element_kind="roof",
        categories=("OST_Roofs",),
        norm_doc=_SP20,
        coarse_kw="уклон кровли",
        citation_anchor="обеспечен уклон кровли не менее 1/200 в одном из направлений",
        topic_keywords=("уклон кровли", "уклон покрытия", "прогиб покрытия"),
        check_question_ru=(
            "Прогибы элементов покрытий должны быть такими, чтобы несмотря на них был "
            "обеспечен уклон кровли не менее 1/200 в одном из направлений, кроме случаев, "
            "оговорённых в других нормативных документах (п.15.1.4 СП20). Проверь фактический "
            "уклон кровли (параметр ROOF_SLOPE, приведённый к форме 1/N) >= 1/200 с учётом "
            "ожидаемого прогиба настила."
        ),
        severity="review",
    ),

    # ── СП 16.13330.2017 — стальные конструкции ──────────────────────────────

    NormLeaf(
        id="kr.steel.column_slenderness_main",
        title_ru="Предельная гибкость основных стальных колонн",
        element_kind="column",
        categories=("OST_StructuralColumns",),
        norm_doc=_SP16,
        coarse_kw="Основные колонны",
        citation_anchor="Основные колонны 180-60",
        topic_keywords=("гибкость", "предельная гибкость", "стальная колонна"),
        check_question_ru=(
            "Предельная гибкость основных колонн — 180-60*альфа, где альфа — коэффициент "
            "использования несущей способности (принимается не менее 0,5) (Таблица 32, "
            "позиция 4, п.10.4.1 СП16). Для элементов группы 4 по ГОСТ 27751 предельная "
            "гибкость повышается на 10% (п.10.4.2). Проверь фактическую гибкость колонны "
            "(l0/i) против этого предела; для колонн из одиночных уголков/труб пространственных "
            "конструкций высотой св. 50 м действует иной предел (см. Таблицу 32 целиком, "
            "позиция 1б — 120)."
        ),
        severity="review",
    ),
    NormLeaf(
        id="kr.steel.bracing_slenderness_limit",
        title_ru="Предельная гибкость элементов связей",
        element_kind="brace",  # modeled as OST_StructuralFraming w/ Brace usage
        categories=("OST_StructuralFraming",),
        norm_doc=_SP16,
        coarse_kw="Элементы связей",
        citation_anchor="стержни, служащие для 200 уменьшения расчетной длины сжатых стержней",
        topic_keywords=("гибкость связей", "элементы связей", "предельная гибкость"),
        check_question_ru=(
            "Предельная гибкость элементов связей (кроме связей между колоннами ниже балок "
            "крановых путей — позиция 5) и стержней, уменьшающих расчётную длину сжатых "
            "элементов — не более 200 (Таблица 32, позиция 6, п.10.4.1 СП16). Проверь "
            "фактическую гибкость связевого элемента <= 200."
        ),
        severity="review",
    ),
]
