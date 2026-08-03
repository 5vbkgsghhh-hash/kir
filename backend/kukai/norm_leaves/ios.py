"""ИОС — Инженерные системы (ОВ / ВК / ЭОМ). Curated leaves (Phase 5 data).

Scope: СП 60.13330.2020 (ОВиК), СП 30.13330.2020 (внутренний водопровод и
канализация), СП 32.13330.2018 (канализация — наружные сети), СП 256.1325800.2016
(электроустановки жилых и общественных зданий), ПУЭ-7 (Правила устройства
электроустановок).

All 11 leaves below are Ярус 2 (grounded model-assist) — BY DESIGN, not by
omission. Every quantified requirement found in these five documents governs a
system/MEP quantity (air/coolant temperature, duct steel thickness, pipe
diameter/depth, hydrostatic head, manhole clearance, socket mounting height/
clearance, cable cross-section) that kukai.norm_control.MODEL_FACTS_CS does not
extract today — the extractor only knows room/door/window/wall/stair geometry.
Each leaf's citation_anchor is nonetheless a REAL, verified clause fragment
(kukai.norm_control.ground_citation, enforced by tests/test_norm_tree.py), so the
model-assist check is always grounded in the actual norm text, never invented.

NOTE — extractor extensions this discipline needs before any of these can close as
Ярус 1 (deterministic) leaves:
  * room{temp_c} — design/standby air temperature per room (ov.heating.standby_min_temp_residential)
  * pipe{temp_c} — heat-carrier (coolant) temperature (ov.heating.max_coolant_temp)
  * duct{thickness_mm} — sheet-steel thickness of fire-rated ductwork (ov.duct.fire_rated_min_thickness)
  * pipe{pressure_m} or system{head_m} — hydrostatic free head at the highest fixture (vk.water.min_free_head)
  * pipe{diameter_mm} — pipe diameter, needed by both vk.water.inlet_pipe_min_diameter
    and vk.sewage.pipe_min_burial_depth's companion diameter branch
  * pipe{depth_m} — burial depth of buried pipe runs (vk.sewage.pipe_min_burial_depth)
  * manhole{diameter_mm} — inspection-well throat diameter (vk.sewage.manhole_access_min_diameter);
    no BuiltInCategory cleanly fits a manhole today (placeholder: OST_GenericModel)
  * socket{height_m} — mounting height of an outlet/switch above finished floor
    (eom.socket.height_children_room)
  * socket{distance_to_m, target}
      — distance from an outlet/switch to a named nearby element (shower-cabin
        doorway / gas pipe) (eom.socket.min_distance_from_shower,
        eom.socket.min_distance_from_gas_pipe)
  * cable{cross_section_mm2} — conductor cross-section of a dedicated circuit
    (eom.cable.electric_stove_min_section)
"""
from __future__ import annotations

from kukai.norm_tree import NormLeaf

_SP60 = "СП 60.13330.2020"
_SP30 = "СП 30.13330.2020"
_SP32 = "СП 32.13330.2018"
_SP256 = "СП 256.1325800.2016"
_PUE7 = "ПУЭ-7"


LEAVES: list[NormLeaf] = [
    # ── ОВ — отопление, вентиляция (СП 60.13330.2020) ───────────────────────

    NormLeaf(
        id="ov.heating.standby_min_temp_residential",
        title_ru="Минимальная температура воздуха в жилых помещениях (нерабочий/аварийный режим)",
        element_kind="room", categories=("OST_Rooms",), norm_doc=_SP60,
        coarse_kw="нерабочее",
        citation_anchor="15 °C - в жилых помещениях",
        topic_keywords=("отопление", "температура воздуха", "дежурное отопление", "жилые помещения"),
        check_question_ru=(
            "В нерабочее время, когда помещения не используются, и при устранении аварий "
            "на системе теплоснабжения — поддерживается ли в жилых помещениях температура "
            "воздуха не ниже 15 °C?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="ov.heating.max_coolant_temp",
        title_ru="Максимальная температура теплоносителя систем отопления (жилые и общественные здания)",
        element_kind="pipe", categories=("OST_PipeCurves",), norm_doc=_SP60,
        coarse_kw="теплоносителя",
        citation_anchor="в жилых и общественных зданиях и комплексах не более 95 °C",
        topic_keywords=("отопление", "теплоноситель", "температура теплоносителя", "система отопления"),
        check_question_ru=(
            "Расчётная температура теплоносителя системы внутреннего теплоснабжения и "
            "отопления в жилом или общественном здании — не более 95 °C?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="ov.duct.fire_rated_min_thickness",
        title_ru="Минимальная толщина стали воздуховодов с нормируемым пределом огнестойкости",
        element_kind="duct", categories=("OST_DuctCurves",), norm_doc=_SP60,
        coarse_kw="огнестойкости",
        citation_anchor="должна быть не менее 0,8 мм",
        topic_keywords=("воздуховод", "огнестойкость", "противодымная вентиляция", "толщина металла"),
        check_question_ru=(
            "Для воздуховодов с нормируемым пределом огнестойкости — толщина листовой стали "
            "(с учётом допусков по приложению К СП 60.13330.2020) не менее 0,8 мм?"
        ),
        severity="review",
    ),

    # ── ВК — водоснабжение (СП 30.13330.2020) и канализация (СП 32.13330.2018) ──

    NormLeaf(
        id="vk.water.min_free_head",
        title_ru="Минимальный свободный напор у наиболее высоко расположенного санитарного прибора",
        element_kind="pipe", categories=("OST_PipeCurves",), norm_doc=_SP30,
        coarse_kw="напор",
        citation_anchor="не менее 20,0 м вод.ст. (0,2 МПа)",
        topic_keywords=("водоснабжение", "напор", "давление воды", "санитарный прибор"),
        check_question_ru=(
            "На отметке наиболее высоко расположенного санитарного прибора обеспечен ли "
            "свободный напор не менее 20,0 м вод.ст. (0,2 МПа) по расчёту системы "
            "хозяйственно-питьевого водоснабжения?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="vk.water.inlet_pipe_min_diameter",
        title_ru="Минимальный диаметр труб на вводе водопровода в здание",
        element_kind="pipe", categories=("OST_PipeCurves",), norm_doc=_SP30,
        coarse_kw="вводах",
        citation_anchor="Диаметры труб на вводах водопровода в здание, независимо от расчета, следует принимать не менее 50 мм",
        topic_keywords=("водоснабжение", "ввод водопровода", "диаметр трубы"),
        check_question_ru=(
            "Диаметр труб на вводе водопровода в здание — не менее 50 мм независимо от "
            "гидравлического расчёта?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="vk.sewage.manhole_access_min_diameter",
        title_ru="Минимальный диаметр горловины смотрового колодца для доступа персонала",
        element_kind="manhole", categories=("OST_GenericModel",), norm_doc=_SP32,
        coarse_kw="эксплуатационного",
        citation_anchor="следует принимать диаметром не менее 700 мм",
        topic_keywords=("канализация", "колодец", "смотровой колодец", "диаметр колодца"),
        check_question_ru=(
            "Горловина смотрового колодца, предназначенного для доступа эксплуатационного "
            "персонала на сетях водоотведения, — диаметром не менее 700 мм?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="vk.sewage.pipe_min_burial_depth",
        title_ru="Минимальная глубина заложения трубопровода канализации (защита от наземного транспорта)",
        element_kind="pipe", categories=("OST_PipeCurves",), norm_doc=_SP32,
        coarse_kw="заложения",
        citation_anchor="глубина заложения должна быть не менее 0,7 м",
        topic_keywords=("канализация", "глубина заложения", "трубопровод", "наружные сети"),
        check_question_ru=(
            "Во избежание повреждения наземным транспортом — глубина заложения трубопровода "
            "до верха трубы не менее 0,7 м (считая от отметки планировки поверхности земли)?"
        ),
        severity="review",
    ),

    # ── ЭОМ — электроустановки (ПУЭ-7, СП 256.1325800.2016) ─────────────────

    NormLeaf(
        id="eom.socket.height_children_room",
        title_ru="Высота установки розеток и выключателей в помещениях для пребывания детей",
        element_kind="socket", categories=("OST_ElectricalFixtures",), norm_doc=_SP256,
        coarse_kw="1,8 м",
        citation_anchor="должны устанавливаться на высоте 1,8 м от пола",
        topic_keywords=("розетка", "выключатель", "высота установки", "дети", "детские учреждения"),
        check_question_ru=(
            "В помещениях для пребывания детей выключатели и розетки установлены на высоте "
            "1,8 м от пола?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="eom.socket.min_distance_from_shower",
        title_ru="Минимальное расстояние от розеток и выключателей до дверного проёма душевой кабины",
        element_kind="socket", categories=("OST_ElectricalFixtures",), norm_doc=_PUE7,
        coarse_kw="душевой",
        citation_anchor="не менее 0,6 м от дверного проема душевой кабины",
        topic_keywords=("розетка", "выключатель", "душевая кабина", "ванная комната", "расстояние"),
        check_question_ru=(
            "Выключатели и штепсельные розетки находятся на расстоянии не менее 0,6 м от "
            "дверного проёма душевой кабины?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="eom.socket.min_distance_from_gas_pipe",
        title_ru="Минимальное расстояние от розеток и выключателей до газопроводов",
        element_kind="socket", categories=("OST_ElectricalFixtures",), norm_doc=_PUE7,
        coarse_kw="газопровод",
        citation_anchor="до газопроводов должно быть не менее 0,5 м",
        topic_keywords=("розетка", "выключатель", "газопровод", "расстояние", "электроустановки"),
        check_question_ru=(
            "Минимальное расстояние от выключателей, штепсельных розеток и элементов "
            "электроустановок до газопроводов — не менее 0,5 м?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="eom.cable.electric_stove_min_section",
        title_ru="Минимальное сечение медных проводников линии питания однофазной электроплиты",
        element_kind="cable", categories=("OST_Wire",), norm_doc=_SP256,
        coarse_kw="электроплит",
        citation_anchor="сечением не менее 6 мм2",
        topic_keywords=("электроплита", "сечение кабеля", "сечение провода", "групповая линия"),
        check_question_ru=(
            "Отдельная групповая линия питания однофазной электроплиты выполнена медными "
            "проводниками сечением не менее 6 мм²?"
        ),
        severity="review",
    ),
]
