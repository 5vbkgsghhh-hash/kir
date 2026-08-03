"""Теплотехника (СП 50.13330.2012 «Тепловая защита зданий») — curated leaves.

All requirements here are Ярус 2 (grounded model-assist), by construction, not by
omission: СП 50's поэлементные требования (5.1-5.2) set the normируемое приведённое
сопротивление теплопередаче R for each envelope element from Таблица 3, but the
table's value itself is a function of градусо-сутки отопительного периода (climate,
region, building group) — there is no single fixed number that is correct for every
building. Hard-coding one row of Таблица 3 as a Ярус-1 ``Requirement`` threshold would
be *wrong* for most projects (a fabrication-by-omission risk), so these stay Ярус 2:
the model is pointed at the real clause/table and asked to compare it against the
project's climate data and the wall/window/roof's actual R — a check no author-set
constant could honestly encode.

A second reason all five leaves are Ярус 2: the current extractor (MODEL_FACTS_CS in
kukai/norm_control.py) does not carry ANY thermal-resistance fact — wall/window facts
today are geometric only (area_m2, height_m / width_m, height_m). See the extractor
extensions noted in the LEAVES docstrings below; until those land, Ярус 1 for this
discipline is not honestly possible.
"""
from __future__ import annotations

from kukai.norm_tree import NormLeaf

_SP50 = "СП 50.13330.2012"

# Shared grounding for the three Таблица-3 poэлементные leaves (wall / window / roof):
# the base normируемое R value for every envelope element type lives in ONE table
# (5.2, формула 5.1), so all three cite the same anchor — the table header is a
# distinctive, verified fragment; the model resolves the specific column (стен /
# окон и балконных дверей / покрытий) and climate row itself from the full table.
_TABLE3_KW = "Базовые значения требуемого сопротивления теплопередаче"
_TABLE3_ANCHOR = (
    "Таблица 3 - Базовые значения требуемого сопротивления теплопередаче "
    "ограждающих конструкций"
)

LEAVES: list[NormLeaf] = [
    NormLeaf(
        id="thermal.envelope.wall.r_req",
        title_ru="Приведённое сопротивление теплопередаче наружных стен",
        element_kind="wall", categories=("OST_Walls",),
        norm_doc=_SP50,
        coarse_kw=_TABLE3_KW,
        citation_anchor=_TABLE3_ANCHOR,
        topic_keywords=(
            "сопротивление теплопередаче", "теплозащита стен", "теплопередача стен",
            "R стены", "утепление стен", "тепловая защита", "thermal resistance wall",
        ),
        check_question_ru=(
            "Определите приведённое сопротивление теплопередаче R стены (м²·°С/Вт, "
            "по составу слоёв конструкции) и сравните его с нормируемым базовым "
            "значением требуемого сопротивления теплопередаче для стен по Таблице 3 "
            "СП 50.13330.2012 (п.5.2, формула 5.1) для градусо-суток отопительного "
            "периода района строительства и группы здания (жилые/общественные/"
            "производственные). Стена соответствует, если R ≥ табличного значения "
            "(п.4 Таблицы 3 отдельно ограничивает предельно допустимое значение при "
            "отклонении от табличных градусо-суток по формуле примечания 1)."
        ),
        severity="review",
    ),
    NormLeaf(
        id="thermal.envelope.window.r_req",
        title_ru="Приведённое сопротивление теплопередаче окон и балконных дверей (светопрозрачная часть)",
        element_kind="window", categories=("OST_Windows",),
        norm_doc=_SP50,
        coarse_kw=_TABLE3_KW,
        citation_anchor=_TABLE3_ANCHOR,
        topic_keywords=(
            "сопротивление теплопередаче окон", "теплозащита окон", "R окна",
            "теплопередача остекления", "энергоэффективные окна", "window thermal resistance",
        ),
        check_question_ru=(
            "Определите приведённое сопротивление теплопередаче R окна/светопрозрачной "
            "части балконной двери (м²·°С/Вт, по типу стеклопакета/профиля) и сравните "
            "его с нормируемым базовым значением для графы «Окон и балконных дверей, "
            "витрин и витражей» Таблицы 3 СП 50.13330.2012 (п.5.2, формула 5.1) для "
            "градусо-суток отопительного периода района строительства и группы здания. "
            "Окно соответствует, если R ≥ табличного значения."
        ),
        severity="review",
    ),
    NormLeaf(
        id="thermal.envelope.roof.r_req",
        title_ru="Приведённое сопротивление теплопередаче покрытий (кровли)",
        element_kind="roof", categories=("OST_Roofs",),
        norm_doc=_SP50,
        coarse_kw=_TABLE3_KW,
        citation_anchor=_TABLE3_ANCHOR,
        topic_keywords=(
            "сопротивление теплопередаче покрытия", "теплозащита кровли", "R кровли",
            "утепление кровли", "теплопередача покрытия", "roof thermal resistance",
        ),
        check_question_ru=(
            "Определите приведённое сопротивление теплопередаче R покрытия/кровли "
            "(м²·°С/Вт, по составу кровельного пирога) и сравните его с нормируемым "
            "базовым значением для графы «Покрытий» Таблицы 3 СП 50.13330.2012 "
            "(п.5.2, формула 5.1) для градусо-суток отопительного периода района "
            "строительства и группы здания. Покрытие соответствует, если R ≥ "
            "табличного значения."
        ),
        severity="review",
    ),
    NormLeaf(
        id="thermal.envelope.door_entrance.r_relative",
        title_ru="Сопротивление теплопередаче входных дверей и ворот (относительно стен)",
        element_kind="door", categories=("OST_Doors",),
        norm_doc=_SP50,
        coarse_kw="входных дверей",
        citation_anchor=(
            "сопротивления теплопередаче входных дверей и ворот должно быть не "
            "менее 0,6 стен зданий"
        ),
        topic_keywords=(
            "входная дверь", "сопротивление теплопередаче двери", "теплозащита входной двери",
            "ворота теплопередача", "entrance door thermal resistance",
        ),
        check_question_ru=(
            "Определите приведённое сопротивление теплопередаче R входной двери/ворот "
            "(м²·°С/Вт) и сравните его с 0,6 × нормируемое сопротивление теплопередаче "
            "стен данного здания (определяемого по формуле 5.4 СП 50.13330.2012). "
            "Дверь/ворота соответствуют, если их R ≥ 0,6 × R стен."
        ),
        severity="review",
    ),
    NormLeaf(
        id="thermal.envelope.door_balcony.opaque_vs_glazed",
        title_ru="Сопротивление теплопередаче глухой части балконных дверей (относительно светопрозрачной части)",
        element_kind="door", categories=("OST_Doors",),
        norm_doc=_SP50,
        coarse_kw="глухой части",
        citation_anchor=(
            "не менее чем в 1,5 раза выше нормируемого значения приведенного "
            "сопротивления теплопередаче"
        ),
        topic_keywords=(
            "балконная дверь", "глухая часть балконной двери", "теплопередача двери",
            "balcony door thermal resistance",
        ),
        check_question_ru=(
            "Определите приведённое сопротивление теплопередаче R глухой (непрозрачной) "
            "части балконной двери и сравните его со светопрозрачной частью той же "
            "двери. Глухая часть соответствует, если её R ≥ 1,5 × R светопрозрачной "
            "части (примечание 2 к Таблице 3 СП 50.13330.2012)."
        ),
        severity="review",
    ),
]
